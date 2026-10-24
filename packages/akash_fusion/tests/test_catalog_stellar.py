import pytest
from akash_core.schemas import AstronomicalObject
from akash_data.base import CatalogRecord
from akash_fusion.catalog_match import match_signal, record_period, star_entry_summary
from akash_fusion.stellar import (
    RUWE_BINARITY_SUSPECT,
    Neighbor,
    StellarProfile,
    StellarService,
    assess_contamination,
)
from conftest import FakeGaia, neighbor, toi


def koi(period, disp="CONFIRMED", native="K00001.01"):
    return CatalogRecord("NASA Exoplanet Archive", "cumulative", native,
                         {"kepoi_name": native, "koi_period": period},
                         {"CONFIRMED": "confirmed", "CANDIDATE": "candidate",
                          "FALSE POSITIVE": "false_positive"}[disp], "q", "uri")


def test_exact_period_match_inherits_catalog_status():
    m = match_signal(3.2, [toi(3.2, "CP")])
    assert m and m.status == "confirmed" and m.relation == "exact" and m.rel_diff == 0
    assert match_signal(3.2, [koi(3.21, "FALSE POSITIVE")]).status == "false_positive"


@pytest.mark.parametrize("sig,cat,relation", [(6.4, 3.2, "harmonic_0.5x"), (1.6, 3.2, "harmonic_2x")])
def test_harmonic_matches_are_labelled(sig, cat, relation):
    m = match_signal(sig, [toi(cat)])
    assert m and m.relation == relation


def test_tolerance_and_non_matches():
    assert match_signal(3.2 * 1.02, [toi(3.2)]) is None  # 2% apart, tolerance is 1%
    assert match_signal(3.2 * 1.009, [toi(3.2)]) is not None
    assert match_signal(5.0, [toi(3.2)]) is None


def test_best_match_prefers_closest_then_exact():
    near, far = toi(3.2, "PC", "1.01"), toi(3.21, "CP", "2.01")
    assert match_signal(3.2, [far, near]).record.native_id == "1.01"
    exact_vs_harm = match_signal(3.2, [toi(6.4, "CP", "h"), toi(3.2, "PC", "e")])
    assert exact_vs_harm.record.native_id == "e"


def test_records_without_period_or_status_are_ignored():
    no_period = CatalogRecord("x", "toi", "a", {"pl_orbper": None}, "confirmed", "q", "u")
    no_status = CatalogRecord("x", "toi", "b", {"pl_orbper": 3.2}, None, "q", "u")
    assert record_period(no_period) is None and match_signal(3.2, [no_period, no_status]) is None
    assert star_entry_summary([toi(1.0, "CP"), toi(2.0, "FP"), no_status]) == {
        "confirmed": 1, "candidate": 0, "false_positive": 1, "unclassified": 1}


def test_profile_extracts_parameters_and_excludes_target_from_neighbours():
    gaia = FakeGaia(neighbors=[neighbor(1, 8.0, 17.0), neighbor(2, 30.0, None)])
    obj = AstronomicalObject(ra_deg=1.0, dec_deg=1.0, canonical_name="x")
    p = StellarService(gaia).profile(obj)
    assert p.source_id == "777" and p.radius_rsun == 1.0 and p.logg == 4.4
    assert [n.source_id for n in p.neighbors] == ["1", "2"]  # target not its own neighbour
    assert p.neighbors[0].delta_g == pytest.approx(5.0) and p.neighbors[1].delta_g is None
    assert p.cone_record.query and p.star_record.query  # provenance material present
    assert p.context().density_solar == pytest.approx(10 ** (4.4 - 4.438), rel=1e-6)


def test_profile_is_none_without_gaia_source():
    class Empty(FakeGaia):
        def lookup(self, obj):
            return []

    assert StellarService(Empty()).profile(AstronomicalObject(ra_deg=1.0, dec_deg=1.0,
                                                              canonical_name="x")) is None


def test_ruwe_binarity_flag():
    mk = lambda r: StellarProfile("1", 12.0, 5000, 4.4, 1.0, r)  # noqa: E731
    assert mk(RUWE_BINARITY_SUSPECT + 0.1).binarity_suspect is True
    assert mk(1.0).binarity_suspect is False and mk(None).binarity_suspect is None


def prof(*neighbors):
    return StellarProfile("1", 12.0, 5000, 4.4, 1.0, 1.0, list(neighbors))


def test_contamination_capability_scales_with_depth_and_brightness():
    # neighbour 5 mag fainter -> flux ratio 0.01 -> ~0.99% of the aperture total
    p = prof(Neighbor("n", 10.0, 17.0, 5.0))
    assert assess_contamination(p, 0.005).verdict == "capable_neighbor"   # 0.5% dip: possible
    assert assess_contamination(p, 0.02).verdict == "none_capable"        # 2% dip: impossible
    p2 = prof(Neighbor("n", 10.0, 22.0, 10.0))                            # 10 mag fainter
    assert assess_contamination(p2, 0.001).verdict == "none_capable"


def test_contamination_respects_aperture_and_unknown_magnitudes():
    far = prof(Neighbor("n", 40.0, 13.0, 1.0))
    a = assess_contamination(far, 0.01)
    assert a.n_in_aperture == 0 and a.verdict == "none_capable"
    unk = assess_contamination(prof(Neighbor("n", 5.0, None, None)), 0.01)
    assert unk.n_unknown_mag == 1 and unk.n_in_aperture == 1 and not unk.capable


def test_neighbours_dilute_each_other():
    """Total aperture flux includes every neighbour, so a lone faint source is judged against
    a larger total when others are present."""
    solo = assess_contamination(prof(Neighbor("a", 5.0, 14.0, 2.0)), 0.13)
    crowded = assess_contamination(
        prof(Neighbor("a", 5.0, 14.0, 2.0), Neighbor("b", 6.0, 12.5, 0.5),
             Neighbor("c", 7.0, 12.5, 0.5)), 0.13)
    assert len(solo.capable) == 1 and all(n.source_id != "a" for n in crowded.capable)


def test_radius_falls_back_to_flame_when_gspphot_is_empty():
    from akash_fusion.stellar import _radius

    assert _radius({"radius_gspphot": None, "radius_flame": 1.12}) == 1.12
    assert _radius({"radius_gspphot": 0.9, "radius_flame": 1.12}) == 0.9
    assert _radius({}) is None


def test_gaia_evidence_claim_states_units_and_missing_values():
    from akash_fusion.evidence import _fmt
    assert _fmt(4890.4, 0, " K") == "4890 K"
    assert _fmt(1.2031, 2, " Rsun") == "1.20 Rsun"
    assert _fmt(None, 2, " Rsun") == "unavailable"
