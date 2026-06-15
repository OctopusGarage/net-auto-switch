import textwrap

import pytest

from net_auto_switch.config import ConfigError, load_config


def _write(tmp_path, content):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_load_minimal_applies_defaults(tmp_path):
    path = _write(
        tmp_path,
        """
        [clash]
        secret = "abc"
    """,
    )
    cfg = load_config(str(path))
    assert cfg.main_interval == 600
    assert cfg.wifi.enabled is True
    assert cfg.wifi.check_interval == 3600
    assert cfg.wifi.switch_cooldown == 7200
    assert cfg.clash.secret == "abc"
    assert cfg.clash.api == "http://127.0.0.1:9097"
    assert cfg.clash.group_priority == ["SG", "Tokyo", "JP_Other"]


def test_override_values(tmp_path):
    path = _write(
        tmp_path,
        """
        main_interval = 300
        [wifi]
        enabled = false
        check_interval = 1800
        [clash]
        secret = "xyz"
        delay_limit = 150
    """,
    )
    cfg = load_config(str(path))
    assert cfg.main_interval == 300
    assert cfg.wifi.enabled is False
    assert cfg.wifi.check_interval == 1800
    assert cfg.clash.delay_limit == 150


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(str(tmp_path / "nope.toml"))
    assert "config.example.toml" in str(e.value)


def test_invalid_interval_raises(tmp_path):
    path = _write(
        tmp_path,
        """
        main_interval = -5
        [clash]
        secret = "abc"
    """,
    )
    with pytest.raises(ConfigError):
        load_config(str(path))


def test_regions_override(tmp_path):
    path = _write(
        tmp_path,
        """
        [clash]
        secret = "abc"
        group_priority = ["US", "JP"]
        [clash.regions]
        US = "(US|美国)"
        JP = "(JP|日本)"
    """,
    )
    cfg = load_config(str(path))
    assert cfg.clash.regions == {"US": "(US|美国)", "JP": "(JP|日本)"}
    assert cfg.clash.group_priority == ["US", "JP"]


def test_legacy_patterns_translate_to_regions(tmp_path):
    # Old [clash.patterns] configs keep working: sg/jp/tokyo -> named regions.
    path = _write(
        tmp_path,
        """
        [clash]
        secret = "abc"
        [clash.patterns]
        sg = "CUSTOM_SG"
        tokyo = "CUSTOM_TK"
        trial = "TRIALX"
    """,
    )
    cfg = load_config(str(path))
    assert cfg.clash.regions["SG"] == "CUSTOM_SG"
    assert cfg.clash.regions["Tokyo"] == "CUSTOM_TK"
    assert cfg.clash.regions["JP_Other"] == "(JP|Japan|日本|🇯🇵)"  # untouched -> default
    assert cfg.clash.trial == "TRIALX"


def test_group_priority_undefined_region_raises(tmp_path):
    path = _write(
        tmp_path,
        """
        [clash]
        secret = "abc"
        group_priority = ["US"]
        [clash.regions]
        JP = "(JP|日本)"
    """,
    )
    with pytest.raises(ConfigError):
        load_config(str(path))


def test_switch_cooldown_zero_allowed(tmp_path):
    path = _write(
        tmp_path,
        """
        [wifi]
        switch_cooldown = 0
        [clash]
        secret = "abc"
    """,
    )
    cfg = load_config(str(path))
    assert cfg.wifi.switch_cooldown == 0
