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
        "mixed-port: 7890\nexternal-controller: 127.0.0.1:9097\nsecret: abc\n",
        encoding="utf-8",
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
    out.write_text(render_config_toml(det, ["SG", "JP"]), encoding="utf-8")

    cfg = load_config(str(out))
    assert cfg.clash.api == "http://127.0.0.1:9097"
    assert cfg.clash.secret == "my secret"
    assert cfg.clash.proxy_port == 7890
    assert cfg.clash.profiles_yaml == "/some/profiles.yaml"
    assert cfg.clash.priority == ["SG", "JP"]
    # defaults preserved for untouched sections
    assert cfg.wifi.enabled is True


def test_detect_regions_counts_and_orders():
    names = ["US-LA 美国", "JP-1 日本", "JP-2 日本", "SG 新加坡", "random-node"]
    d = detect_regions(names)
    assert d["JP"] == 2
    assert d["US"] == 1
    assert d["SG"] == 1
    assert list(d)[0] == "JP"  # sorted by count, desc


def test_render_emits_priority_and_cities(tmp_path):
    d = DetectedClash(api="http://127.0.0.1:9097", secret="s", proxy_port=7890, profiles_yaml="/p")
    out = render_config_toml(d, ["SG", "JP"], cities={"JP": ["Tokyo"]})
    path = tmp_path / "config.toml"
    path.write_text(out, encoding="utf-8")
    cfg = load_config(str(path))
    assert cfg.clash.priority == ["SG", "JP"]
    assert cfg.clash.cities == {"JP": ["Tokyo"]}
    assert "[clash.regions]" not in out
    assert "group_priority" not in out


def test_detect_regions_uses_country_codes():
    names = ["US-LA 美国", "JP-1 日本", "JP-2 日本", "SG 新加坡", "random"]
    d = detect_regions(names)
    assert d["JP"] == 2 and d["US"] == 1 and d["SG"] == 1
    assert list(d)[0] == "JP"


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


def test_render_config_toml_with_cities(tmp_path):
    det = DetectedClash(
        api="http://127.0.0.1:9097", secret="x", proxy_port=7890, profiles_yaml="/p.yaml"
    )
    cities = {"JP": ["Tokyo", "Osaka"]}
    out = tmp_path / "config.toml"
    out.write_text(render_config_toml(det, ["US", "JP"], cities=cities), encoding="utf-8")

    cfg = load_config(str(out))
    assert cfg.clash.priority == ["US", "JP"]
    assert cfg.clash.cities == {"JP": ["Tokyo", "Osaka"]}


def test_parse_index_order():
    from net_auto_switch.setup import parse_index_order

    items = ["HK", "SG", "JP", "US"]
    assert parse_index_order("1 3 4", items) == (["HK", "JP", "US"], [])
    assert parse_index_order("2,2, 1", items) == (["SG", "HK"], [])  # dedupe, order kept
    assert parse_index_order("9 x 1", items) == (["HK"], ["9", "x"])  # out-of-range / nonnum
    assert parse_index_order("  ", items) == ([], [])  # empty -> caller defaults


def test_detect_cities():
    from net_auto_switch.setup import detect_cities

    names = ["JP-Tokyo 东京 01", "JP Osaka 大阪", "Osaka-2 大阪", "US-LA 洛杉矶", "SG 新加坡", "x"]
    d = detect_cities(names)
    assert d["JP"] == {"Osaka": 2, "Tokyo": 1}  # sorted by count desc
    assert d["US"] == {"Los Angeles": 1}
    assert "SG" not in d  # no city detected
