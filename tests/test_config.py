import textwrap

import pytest

from net_auto_switch.config import ConfigError, load_config


def _write(tmp_path, content):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(content))
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


def test_patterns_override(tmp_path):
    path = _write(
        tmp_path,
        """
        [clash]
        secret = "abc"
        [clash.patterns]
        sg = "CUSTOM_SG"
        tokyo = "CUSTOM_TK"
    """,
    )
    cfg = load_config(str(path))
    assert cfg.clash.patterns.sg == "CUSTOM_SG"
    assert cfg.clash.patterns.tokyo == "CUSTOM_TK"
    # untouched pattern keeps default
    assert cfg.clash.patterns.jp == "(JP|Japan|日本|🇯🇵)"


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
