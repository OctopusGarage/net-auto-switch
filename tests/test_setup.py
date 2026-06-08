from net_auto_switch.config import load_config
from net_auto_switch.setup import (
    DetectedClash,
    detect_clash_verge,
    parse_verge_runtime,
    render_config_toml,
)


def test_parse_verge_runtime_basic():
    text = "mixed-port: 7890\nexternal-controller: 127.0.0.1:9097\nsecret: s3cr3t\n"
    d = parse_verge_runtime(text)
    assert d["api"] == "http://127.0.0.1:9097"
    assert d["secret"] == "s3cr3t"
    assert d["proxy_port"] == 7890


def test_parse_verge_runtime_wildcard_host_and_empty_secret():
    text = "external-controller: 0.0.0.0:9097\nsecret: ''\nport: 7891\n"
    d = parse_verge_runtime(text)
    assert d["api"] == "http://127.0.0.1:9097"  # 0.0.0.0 normalized to loopback
    assert d["secret"] == ""
    assert d["proxy_port"] == 7891  # falls back to `port` when no mixed-port


def test_parse_verge_runtime_defaults_when_absent():
    d = parse_verge_runtime("foo: bar\n")
    assert d["api"] == "http://127.0.0.1:9097"
    assert d["proxy_port"] == 7890


def test_detect_clash_verge_reads_dir(tmp_path):
    (tmp_path / "clash-verge.yaml").write_text(
        "mixed-port: 7890\nexternal-controller: 127.0.0.1:9097\nsecret: abc\n"
    )
    det = detect_clash_verge(str(tmp_path))
    assert det is not None
    assert det.api == "http://127.0.0.1:9097"
    assert det.secret == "abc"
    assert det.proxy_port == 7890
    assert det.profiles_yaml.endswith("profiles.yaml")


def test_detect_clash_verge_missing(tmp_path):
    assert detect_clash_verge(str(tmp_path)) is None


def test_render_config_toml_roundtrips(tmp_path):
    det = DetectedClash(
        api="http://127.0.0.1:9097",
        secret="my secret",  # space exercises proper quoting
        proxy_port=7890,
        profiles_yaml="/some/profiles.yaml",
    )
    out = tmp_path / "config.toml"
    out.write_text(render_config_toml(det, ["SG", "Tokyo"]))

    cfg = load_config(str(out))
    assert cfg.clash.api == "http://127.0.0.1:9097"
    assert cfg.clash.secret == "my secret"
    assert cfg.clash.proxy_port == 7890
    assert cfg.clash.profiles_yaml == "/some/profiles.yaml"
    assert cfg.clash.group_priority == ["SG", "Tokyo"]
    # defaults preserved for untouched sections
    assert cfg.wifi.enabled is True
    assert cfg.clash.regions["Tokyo"] == "(Tokyo|东京)"
