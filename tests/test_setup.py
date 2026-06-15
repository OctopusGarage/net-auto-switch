from net_auto_switch.config import load_config
from net_auto_switch.setup import (
    DetectedClash,
    clash_verge_diagnosis,
    detect_clash_verge,
    detect_regions,
    parse_subscriptions,
    parse_verge_runtime,
    render_config_toml,
    resolve_priority,
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
    out.write_text(render_config_toml(det, ["SG", "Tokyo"]), encoding="utf-8")

    cfg = load_config(str(out))
    assert cfg.clash.api == "http://127.0.0.1:9097"
    assert cfg.clash.secret == "my secret"
    assert cfg.clash.proxy_port == 7890
    assert cfg.clash.profiles_yaml == "/some/profiles.yaml"
    assert cfg.clash.group_priority == ["SG", "Tokyo"]
    # defaults preserved for untouched sections
    assert cfg.wifi.enabled is True
    assert cfg.clash.regions["Tokyo"] == "(Tokyo|东京)"


def test_detect_regions_counts_and_orders():
    names = ["US-LA 美国", "JP-1 日本", "JP-2 日本", "SG 新加坡", "random-node"]
    d = detect_regions(names)
    assert d["JP"] == 2
    assert d["US"] == 1
    assert d["SG"] == 1
    assert list(d)[0] == "JP"  # sorted by count, desc
    assert "Tokyo" not in d  # no Tokyo-named node


def test_parse_subscriptions():
    text = """
    items:
      - type: merge
        name: null
      - uid: abc
        type: remote
        name: default
        extra:
          upload: 10
          download: 90
          total: 1000
          expire: 1881446400
        option:
          update_interval: 30
          allow_auto_update: true
    """
    subs = parse_subscriptions(text)
    assert len(subs) == 1  # only the remote item
    s = subs[0]
    assert s["name"] == "default"
    assert s["update_interval"] == 30
    assert s["allow_auto_update"] is True
    assert s["expire"] == 1881446400
    assert s["used"] == 100
    assert s["total"] == 1000


def test_parse_subscriptions_empty():
    assert parse_subscriptions("foo: bar\n") == []


def test_resolve_priority():
    valid = ["JP", "SG", "US"]
    assert resolve_priority("JP,SG", valid) == (["JP", "SG"], [])
    assert resolve_priority("jp, us", valid) == (["JP", "US"], [])  # case-insensitive
    assert resolve_priority("JP,XX", valid) == (["JP"], ["XX"])  # invalid token reported
    assert resolve_priority("JP,jp", valid) == (["JP"], [])  # de-duplicated
    assert resolve_priority(" JP , , SG ", valid) == (["JP", "SG"], [])  # blanks ignored


def test_clash_verge_diagnosis_states(tmp_path):
    missing_app = str(tmp_path / "NoApp.app")

    # nothing installed
    msg = clash_verge_diagnosis(str(tmp_path / "nope"), missing_app)
    assert "doesn't appear to be installed" in msg

    # app present but never run (no config dir)
    app = tmp_path / "Clash Verge.app"
    app.mkdir()
    msg = clash_verge_diagnosis(str(tmp_path / "nope"), str(app))
    assert "hasn't run yet" in msg

    # config dir exists but no clash-verge.yaml
    cfg_dir = tmp_path / "cv"
    cfg_dir.mkdir()
    msg = clash_verge_diagnosis(str(cfg_dir), missing_app)
    assert "no clash-verge.yaml" in msg


def test_render_config_toml_custom_regions(tmp_path):
    det = DetectedClash(
        api="http://127.0.0.1:9097", secret="x", proxy_port=7890, profiles_yaml="/p.yaml"
    )
    regions = {"US": r"(US|美国)", "JP": r"(JP|日本)"}
    out = tmp_path / "config.toml"
    out.write_text(render_config_toml(det, ["US", "JP"], regions), encoding="utf-8")

    cfg = load_config(str(out))
    assert list(cfg.clash.regions) == ["US", "JP"]
    assert cfg.clash.group_priority == ["US", "JP"]
