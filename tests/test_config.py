import textwrap

import pytest

from net_auto_switch.config import DEFAULT_PRIORITY, ClashConfig, ConfigError, load_config


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
    assert cfg.clash.priority == DEFAULT_PRIORITY


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
    assert cfg.clash.region_overrides == {"US": "(US|美国)", "JP": "(JP|日本)"}
    assert cfg.clash.priority == ["US", "JP"]


def test_legacy_patterns_translate_to_regions(tmp_path):
    # Old [clash.patterns] configs keep working: sg/jp/tokyo -> region_overrides.
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
    assert cfg.clash.region_overrides["SG"] == "CUSTOM_SG"
    assert cfg.clash.region_overrides["Tokyo"] == "CUSTOM_TK"
    assert "JP_Other" not in cfg.clash.region_overrides  # not specified -> absent
    assert cfg.clash.trial == "TRIALX"


def test_legacy_group_priority_with_regions_loads(tmp_path):
    # Legacy config with group_priority + [clash.regions]: loads cleanly.
    # group_priority maps to priority; regions maps to region_overrides.
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
    cfg = load_config(str(path))
    assert cfg.clash.priority == ["US"]
    assert cfg.clash.region_overrides == {"JP": "(JP|日本)"}


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


def test_defaults_have_priority_and_empty_cities():
    c = ClashConfig()
    assert isinstance(c.priority, list) and c.priority
    assert c.cities == {}
    assert c.region_overrides == {}


def test_load_priority_and_cities(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'secret = "x"\n'
        "[clash]\n"
        'priority = ["SG", "JP", "US"]\n'
        "[clash.cities]\n"
        'JP = ["Tokyo", "Osaka"]\n',
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.clash.priority == ["SG", "JP", "US"]
    assert cfg.clash.cities == {"JP": ["Tokyo", "Osaka"]}


def test_legacy_group_priority_maps_to_priority(tmp_path):
    # Real legacy configs use region names (incl. city-level), not country codes.
    p = tmp_path / "config.toml"
    p.write_text(
        'secret = "x"\n[clash]\ngroup_priority = ["SG", "Tokyo", "JP_Other"]\n', encoding="utf-8"
    )
    cfg = load_config(str(p))
    assert cfg.clash.priority == ["SG", "JP"]  # SG->SG, Tokyo->JP, JP_Other->JP, deduped


def test_legacy_group_priority_country_codes(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'secret = "x"\n[clash]\nregions = { JP = "(JP|日本)" }\ngroup_priority = ["JP"]\n',
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.clash.priority == ["JP"]


def test_blacklist_config_and_state_dir(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'secret = "x"\n[clash.blacklist]\n'
        'countries = ["CN", "HK"]\noperators = ["腾讯云"]\nrelearn_days = 3\n',
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.clash.blacklist["countries"] == ["CN", "HK"]
    assert cfg.clash.blacklist["operators"] == ["腾讯云"]
    assert cfg.clash.blacklist["relearn_days"] == 3
    assert cfg.clash.state_dir == str(tmp_path)


def test_blacklist_defaults_empty():
    from net_auto_switch.config import ClashConfig

    c = ClashConfig()
    assert c.blacklist == {} and c.state_dir == ""


def test_reachability_loaded_from_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[clash]\nsecret = "x"\npriority = ["JP"]\n\n'
        "[clash.reachability]\n"
        'required = ["web.telegram.org", "https://youtube.com"]\n'
        "timeout_ms = 2500\n",
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.clash.reachability["required"] == ["web.telegram.org", "https://youtube.com"]
    assert cfg.clash.reachability["timeout_ms"] == 2500


def test_reachability_absent_defaults_empty(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[clash]\nsecret = "x"\npriority = ["JP"]\n', encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.clash.reachability == {}


def test_reachability_rejects_non_positive_timeout(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[clash]\nsecret = "x"\npriority = ["JP"]\n\n'
        '[clash.reachability]\nrequired = ["x"]\ntimeout_ms = 0\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(str(p))
