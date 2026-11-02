import pytest

from relkit.version import bump, compare, parse


def test_parse_plain():
    assert parse("1.2.3") == (1, 2, 3)


def test_parse_strips_v_prefix():
    assert parse("v0.3.0") == (0, 3, 0)


def test_parse_drops_prerelease_and_build():
    assert parse("1.2.3-rc.1") == (1, 2, 3)
    assert parse("1.2.3+build.5") == (1, 2, 3)


def test_parse_rejects_short_version():
    with pytest.raises(ValueError):
        parse("1.2")


def test_bump_patch():
    assert bump("0.3.0") == "0.3.1"


def test_bump_minor_resets_patch():
    assert bump("0.3.4", "minor") == "0.4.0"


def test_bump_major_resets_rest():
    assert bump("0.3.4", "major") == "1.0.0"


def test_bump_rejects_unknown_part():
    with pytest.raises(ValueError):
        bump("0.3.0", "epoch")


def test_compare_orders_versions():
    assert compare("0.3.0", "0.4.0") == -1
    assert compare("1.0.0", "1.0.0") == 0
    assert compare("2.0.0", "1.9.9") == 1
