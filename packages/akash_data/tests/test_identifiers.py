import pytest
from akash_core.errors import ValidationFailure
from akash_data.identifiers import adql_literal, parse_identifier


@pytest.mark.parametrize("q,ns,ident", [
    ("TIC 261136679", "TIC", "261136679"), ("tic_261136679", "TIC", "261136679"),
    ("KIC 8462852", "KIC", "8462852"), ("kic-8462852", "KIC", "8462852"),
    ("Gaia DR3 2081900940499099136", "GAIA_DR3", "2081900940499099136"),
    ("Gaia 2081900940499099136", "GAIA_DR3", "2081900940499099136"),
    ("Gaia DR2 2081900940499099136", "GAIA_DR2", "2081900940499099136"),
    ("TOI-700", "TOI", "700"), ("TOI 700.01", "TOI", "700.01"), ("KOI-7016.01", "KOI", "7016.01"),
    ("SDSS J123456.78+123456.7", "SDSS", "123456.78+123456.7"),
])
def test_alias_forms(q, ns, ident):
    p = parse_identifier(q)
    assert (p.kind, p.namespace, p.identifier) == ("alias", ns, ident)


def test_simbad_form():
    assert parse_identifier("tic 5").simbad_form == "TIC 5"
    assert parse_identifier("Gaia 123456").simbad_form == "Gaia DR3 123456"


def test_decimal_coords():
    p = parse_identifier("301.5644, 44.4569")
    assert p.kind == "coords" and p.ra_deg == pytest.approx(301.5644)


def test_sexagesimal_coords():
    p = parse_identifier("19h06m15.5s +44d27m24s")
    assert p.kind == "coords"
    assert p.ra_deg == pytest.approx((19 + 6 / 60 + 15.5 / 3600) * 15)
    assert p.dec_deg == pytest.approx(44 + 27 / 60 + 24 / 3600)


def test_negative_dec_sexagesimal():
    assert parse_identifier("00 42 44.3 -00 16 09").dec_deg < 0


@pytest.mark.parametrize("bad", ["400 10", "10 95", "25h00m00s +10d00m00s", "", "   "])
def test_bad_coords_or_empty(bad):
    with pytest.raises(ValidationFailure):
        parse_identifier(bad)


def test_name_fallthrough():
    p = parse_identifier("Tabby's star".replace("'", ""))
    assert p.kind == "name"


@pytest.mark.parametrize("evil", ["x'; DROP TABLE basic; --", "a' OR '1'='1", "name;select"])
def test_injection_rejected(evil):
    with pytest.raises(ValidationFailure):
        parse_identifier(evil)
    with pytest.raises(ValidationFailure):
        adql_literal(evil)
