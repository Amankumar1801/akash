import pytest
from akash_data.positions import angular_sep_arcsec, clear_winner, propagate


def test_sep_one_arcsec_in_dec():
    assert angular_sep_arcsec(10.0, 0.0, 10.0, 1 / 3600) == pytest.approx(1.0, rel=1e-6)


def test_sep_ra_scales_with_cos_dec():
    s = angular_sep_arcsec(10.0, 60.0, 10.0 + 1 / 3600, 60.0)
    assert s == pytest.approx(0.5, rel=1e-3)


def test_propagate_dec_and_ra():
    ra, dec = propagate(100.0, 0.0, 1000.0, 2000.0, 2000.0, 2016.0)
    assert dec == pytest.approx(2000.0 * 16 / 3.6e6)
    assert ra == pytest.approx(100.0 + 1000.0 * 16 / 3.6e6)


def test_propagate_no_pm_is_identity():
    assert propagate(1.0, 2.0, None, None, 2000, 2016) == (1.0, 2.0)


def test_propagation_improves_match_for_high_pm_star():
    # Barnard's-star-like proper motion: ~10 arcsec/yr -> ~160 arcsec over 16 yr
    ra0, dec0 = 269.45, 4.69
    pmra, pmdec = -798.0, 10328.0
    ra16, dec16 = propagate(ra0, dec0, pmra, pmdec, 2000.0, 2016.0)
    assert angular_sep_arcsec(ra0, dec0, ra16, dec16) > 100


def test_clear_winner_rules():
    assert clear_winner([0.5])
    assert clear_winner([0.2, 5.0])
    assert not clear_winner([0.5, 0.9])
    assert not clear_winner([1.0, 2.5])
