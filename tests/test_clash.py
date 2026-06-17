from unittest import mock

from net_auto_switch.clash import (
    ClashController,
    aggregate_connections,
    summarize_connections,
)
from net_auto_switch.config import ClashConfig


def test_summarize_connections_maps_host_node_rule():
    conns = [
        {
            "metadata": {
                "host": "example.com",
                "destinationIP": "1.2.3.4",
                "destinationPort": "443",
                "network": "TCP",
            },
            "chains": ["JP-1", "Proxy"],  # chains[0] is the actual outbound node
            "rule": "DomainSuffix",
            "rulePayload": "example.com",
        },
        {
            "metadata": {
                "host": "",  # no SNI/host -> falls back to the destination IP
                "destinationIP": "8.8.8.8",
                "destinationPort": "53",
                "network": "udp",
            },
            "chains": ["DIRECT"],
            "rule": "GEOIP",
            "rulePayload": "CN",
        },
    ]
    by_host = {r.host: r for r in summarize_connections(conns)}

    assert by_host["example.com"].node == "JP-1"
    assert by_host["example.com"].dest_ip == "1.2.3.4"
    assert by_host["example.com"].rule == "DomainSuffix(example.com)"
    assert by_host["example.com"].network == "tcp"
    # host empty -> shows the destination IP, node is DIRECT
    assert by_host["8.8.8.8"].node == "DIRECT"
    assert by_host["8.8.8.8"].rule == "GEOIP(CN)"


def test_summarize_connections_handles_missing_fields():
    rows = summarize_connections([{}])
    assert rows[0].host == ""
    assert rows[0].node == "?"
    assert rows[0].rule == ""


def test_aggregate_connections_folds_by_host_and_node():
    conns = [
        {
            "metadata": {"host": "t.org", "destinationIP": ""},
            "chains": ["JP"],
            "rule": "DomainSuffix",
            "rulePayload": "t.org",
        },
        {"metadata": {"host": "t.org", "destinationIP": "1.1.1.1"}, "chains": ["JP"]},
        {"metadata": {"host": "a.com"}, "chains": ["JP"]},
    ]
    groups = aggregate_connections(summarize_connections(conns))
    by = {(g.host, g.node): g for g in groups}

    assert by[("t.org", "JP")].count == 2
    assert by[("t.org", "JP")].dest_ip == "1.1.1.1"  # first non-empty IP kept
    assert by[("t.org", "JP")].rule == "DomainSuffix(t.org)"
    assert by[("a.com", "JP")].count == 1


def test_summarize_connections_sorted_by_host_then_node():
    conns = [
        {"metadata": {"host": "b.com"}, "chains": ["N2"]},
        {"metadata": {"host": "a.com"}, "chains": ["N2"]},
        {"metadata": {"host": "a.com"}, "chains": ["N1"]},
    ]
    rows = summarize_connections(conns)
    assert [(r.host, r.node) for r in rows] == [
        ("a.com", "N1"),
        ("a.com", "N2"),
        ("b.com", "N2"),
    ]


def make_ctrl(priority=None, cities=None, blacklist=None, state_dir="", **kw):
    cfg = ClashConfig(
        secret="x",
        priority=priority or ["SG", "JP"],
        cities=cities or {},
        blacklist=blacklist if blacklist is not None else {},
        state_dir=state_dir,
        **kw,
    )
    return ClashController(cfg)


# ----- two-level grouping -----


def test_group_key_city_enabled_country():
    c = make_ctrl(priority=["JP"], cities={"JP": ["Tokyo"]})
    assert c.group_key("JP Tokyo 01") == "JP/Tokyo"
    assert c.group_key("Japan Osaka 02") == "JP/_other"


def test_group_key_flat_country():
    c = make_ctrl(priority=["US"], cities={})
    assert c.group_key("US-LA 美国") == "US"


def test_grouping_two_level_excludes_trial():
    c = make_ctrl(priority=["SG", "JP"], cities={"JP": ["Tokyo"]})
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "sg1"},
        "sg1": {"type": "Shadowsocks"},
        "试用-jp": {"type": "Shadowsocks"},
        "JP Tokyo 1": {"type": "Vmess"},
        "Japan Plain 2": {"type": "Vmess"},
    }
    g = c.get_all_nodes_by_group(proxies)
    assert g["JP/Tokyo"] == ["JP Tokyo 1"]
    assert g["JP/_other"] == ["Japan Plain 2"]
    assert all("试用" not in n for nodes in g.values() for n in nodes)


def test_derived_chain_country_contiguous():
    c = make_ctrl(priority=["SG", "JP", "US"], cities={"JP": ["Tokyo", "Osaka"]})
    assert c.derived_chain() == ["SG", "JP/Tokyo", "JP/Osaka", "JP/_other", "US"]


def test_select_exhausts_same_country_before_leaving():
    c = make_ctrl(priority=["JP", "SG"], cities={"JP": ["Tokyo", "Osaka"]})
    groups = {"JP/Tokyo": ["t1"], "JP/Osaka": ["o1"], "SG": ["s1"]}
    delays = {"t1": 9999, "o1": 120, "s1": 50}
    switch, target = c.select_node("t1", "JP/Tokyo", groups, delays)
    assert switch is True and target == "o1"


def test_select_stability_first():
    c = make_ctrl(priority=["JP"], cities={})
    switch, target = c.select_node("j1", "JP", {"JP": ["j1"]}, {"j1": 100})
    assert switch is False and target is None


def test_grouping_excludes_trial_and_selectors():
    c = make_ctrl(priority=["SG", "JP"], cities={"JP": ["Tokyo"]})
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "SG-01"},
        "SG-01 新加坡": {"type": "Shadowsocks"},
        "试用-jp": {"type": "Shadowsocks"},
        "JP Tokyo 1": {"type": "Vmess"},
    }
    groups = c.get_all_nodes_by_group(proxies)
    assert groups["SG"] == ["SG-01 新加坡"]
    assert groups["JP/Tokyo"] == ["JP Tokyo 1"]
    assert all("试用" not in n for g in groups.values() for n in g)


# ----- select_node -----


def test_select_node_stable_no_switch():
    c = make_ctrl()
    groups = {"SG": ["sg1"], "JP": []}
    delays = {"sg1": 100}
    assert c.select_node("sg1", "SG", groups, delays) == (False, None)


def test_select_node_switch_within_current_group():
    c = make_ctrl()
    groups = {"SG": ["sg1", "sg2"], "JP": []}
    delays = {"sg1": 400, "sg2": 120}
    assert c.select_node("sg1", "SG", groups, delays) == (True, "sg2")


def test_select_node_downgrade_to_next_group():
    c = make_ctrl(priority=["SG", "JP"], cities={})
    groups = {"SG": ["sg1"], "JP": ["jp1"]}
    delays = {"sg1": 9999, "jp1": 150}
    assert c.select_node("sg1", "SG", groups, delays) == (True, "jp1")


def test_select_node_all_dead_no_switch():
    c = make_ctrl(priority=["SG", "JP"], cities={})
    groups = {"SG": ["sg1"], "JP": ["jp1"]}
    delays = {"sg1": 9999, "jp1": 9999}
    assert c.select_node("sg1", "SG", groups, delays) == (False, None)


def test_select_best_in_group_excludes_timeout():
    c = make_ctrl()
    assert c.select_best_in_group(["a", "b"], {"a": 9999, "b": 300}) == "b"


def test_select_best_in_group_empty():
    c = make_ctrl()
    assert c.select_best_in_group([], {}) is None


def test_run_cycle_dry_run_does_not_switch():
    c = make_ctrl()
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "jp1"},
        "jp1": {"type": "Shadowsocks"},
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="global"),
        mock.patch.object(c, "test_all_delays", return_value={"jp1": 100}),
        mock.patch.object(c, "switch_proxy") as switch,
    ):
        result = c.run_cycle(dry_run=True)
    switch.assert_not_called()
    assert result is False


def test_switch_proxy_targets_given_group():
    c = make_ctrl()
    with mock.patch("net_auto_switch.clash.requests.put") as put:
        put.return_value.status_code = 204
        ok = c.switch_proxy("node-x", "Proxy")
    assert ok
    assert put.call_args[0][0].endswith("/proxies/Proxy")
    assert put.call_args[1]["json"] == {"name": "node-x"}


def test_run_cycle_notifies_on_switch_when_enabled():
    c = ClashController(ClashConfig(secret="x"), notify=True)
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "JP Tokyo dead"},
        "JP Tokyo dead": {"type": "Vmess"},
        "JP Tokyo good": {"type": "Vmess"},
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="global"),
        mock.patch.object(
            c,
            "test_all_delays",
            return_value={"JP Tokyo dead": 9999, "JP Tokyo good": 100},
        ),
        mock.patch.object(c, "switch_proxy"),
        mock.patch.object(c, "query_exit", return_value=("US", "AWS")),
        mock.patch("net_auto_switch.notify.send") as send,
    ):
        c.run_cycle(dry_run=False)
    send.assert_called_once()
    assert send.call_args[0][1] == "JP Tokyo good"  # message = target node
    assert "AWS (US)" in send.call_args[0][2]  # subtitle carries the operator


def test_run_cycle_does_not_notify_when_disabled():
    c = ClashController(ClashConfig(secret="x"))  # notify defaults False
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "JP Tokyo dead"},
        "JP Tokyo dead": {"type": "Vmess"},
        "JP Tokyo good": {"type": "Vmess"},
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="global"),
        mock.patch.object(
            c,
            "test_all_delays",
            return_value={"JP Tokyo dead": 9999, "JP Tokyo good": 100},
        ),
        mock.patch.object(c, "switch_proxy"),
        mock.patch.object(c, "query_exit", return_value=("US", "AWS")),
        mock.patch("net_auto_switch.notify.send") as send,
    ):
        c.run_cycle(dry_run=False)
    send.assert_not_called()


def test_run_cycle_skips_profile_fallback_on_non_macos():
    # All nodes dead would normally trigger the AppleScript profile fallback; on
    # non-macOS that's skipped and the cycle just returns without touching profiles.
    c = ClashController(ClashConfig(secret="x"))
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "JP Tokyo dead"},
        "JP Tokyo dead": {"type": "Vmess"},
    }
    with (
        mock.patch("net_auto_switch.clash.sys.platform", "linux"),
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="global"),
        mock.patch.object(c, "test_all_delays", return_value={"JP Tokyo dead": 9999}),
        mock.patch.object(c, "get_profiles") as get_profiles,
        mock.patch.object(c, "switch_profile_by_name") as switch_profile,
    ):
        result = c.run_cycle(dry_run=False)
    get_profiles.assert_not_called()
    switch_profile.assert_not_called()
    assert result is False


def test_get_exit_operator_maps_isp_via_hints():
    c = make_ctrl()
    payload = {"isp": "Amazon.com, Inc.", "org": "AWS EC2", "country_code": "US"}
    with mock.patch("net_auto_switch.clash.requests.get") as get:
        get.return_value.json.return_value = payload
        assert c.get_exit_operator() == "AWS / Amazon (US)"


def test_get_exit_operator_falls_back_to_isp_string():
    c = make_ctrl()
    payload = {"isp": "Some Local Telecom", "org": "", "country_code": "JP"}
    with mock.patch("net_auto_switch.clash.requests.get") as get:
        get.return_value.json.return_value = payload
        assert c.get_exit_operator() == "Some Local Telecom (JP)"


def test_get_exit_operator_returns_empty_on_error():
    c = make_ctrl()
    with mock.patch("net_auto_switch.clash.requests.get", side_effect=RuntimeError("boom")):
        assert c.get_exit_operator() == ""


def test_run_cycle_dry_run_does_not_probe_exit_operator():
    # A dead current node would normally trigger a switch; under dry-run no switch
    # happens, so the exit-operator IP probe must never fire (ADR-0003).
    c = make_ctrl()
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "JP Tokyo dead"},
        "JP Tokyo dead": {"type": "Vmess"},
        "JP Tokyo good": {"type": "Vmess"},
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="global"),
        mock.patch.object(
            c,
            "test_all_delays",
            return_value={"JP Tokyo dead": 9999, "JP Tokyo good": 100},
        ),
        mock.patch.object(c, "query_exit") as op,
    ):
        c.run_cycle(dry_run=True)
    op.assert_not_called()


# ----- managed group resolution -----


def test_resolve_explicit_override_wins_without_reading_mode():
    c = ClashController(ClashConfig(secret="x", managed_group="Proxy"))
    with mock.patch.object(c, "get_mode") as get_mode:
        assert c.resolve_managed_group({}) == "Proxy"
    get_mode.assert_not_called()


def test_resolve_global_mode_uses_global():
    c = make_ctrl()  # managed_group defaults to "auto"
    with mock.patch.object(c, "get_mode", return_value="global"):
        assert c.resolve_managed_group({}) == "GLOBAL"


def test_resolve_direct_mode_skips():
    c = make_ctrl()
    with mock.patch.object(c, "get_mode", return_value="direct"):
        assert c.resolve_managed_group({}) is None


def test_resolve_rule_mode_detects_busiest_entry_group():
    c = make_ctrl()
    proxies = {
        "Proxy": {"type": "Selector", "now": "n1"},
        "Auto": {"type": "URLTest", "now": "n1"},
    }
    conns = [
        {"chains": ["n1", "Proxy"]},
        {"chains": ["n2", "Proxy"]},
        {"chains": ["n3", "Auto"]},  # URLTest, not a Selector -> ignored
        {"chains": ["DIRECT"]},  # no group -> ignored
    ]
    with (
        mock.patch.object(c, "get_mode", return_value="rule"),
        mock.patch.object(c, "get_connections", return_value=conns),
    ):
        assert c.resolve_managed_group(proxies) == "Proxy"


def test_resolve_rule_mode_falls_back_to_global_when_no_connections():
    c = make_ctrl()
    with (
        mock.patch.object(c, "get_mode", return_value="rule"),
        mock.patch.object(c, "get_connections", return_value=[]),
    ):
        assert c.resolve_managed_group({"GLOBAL": {"type": "Selector"}}) == "GLOBAL"


def test_run_cycle_switches_resolved_managed_group():
    # GLOBAL points at a healthy node, but the rule-mode entry group `Proxy` is
    # stuck on a dead one — the daemon must follow the resolved group, not GLOBAL.
    c = ClashController(ClashConfig(secret="x"))  # auto
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "JP Tokyo good"},
        "Proxy": {"type": "Selector", "now": "JP Tokyo dead"},
        "JP Tokyo dead": {"type": "Vmess"},
        "JP Tokyo good": {"type": "Vmess"},
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="rule"),
        mock.patch.object(
            c, "get_connections", return_value=[{"chains": ["JP Tokyo dead", "Proxy"]}]
        ),
        mock.patch.object(
            c,
            "test_all_delays",
            return_value={"JP Tokyo dead": 9999, "JP Tokyo good": 100},
        ),
        mock.patch.object(c, "switch_proxy") as switch,
        mock.patch.object(c, "query_exit", return_value=("US", "AWS")) as op,
    ):
        c.run_cycle(dry_run=False)
    switch.assert_called_once_with("JP Tokyo good", "Proxy")
    op.assert_called_once()  # exit operator is probed after a real switch


def test_run_cycle_missing_managed_group_skips_without_switching():
    c = ClashController(ClashConfig(secret="x", managed_group="Proxy"))
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "jp1"},
        "jp1": {"type": "Vmess"},
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "switch_proxy") as switch,
    ):
        result = c.run_cycle(dry_run=False)
    switch.assert_not_called()
    assert result is False


def test_us_city_grouping_natural_spelling():
    c = make_ctrl(priority=["US"], cities={"US": ["Los Angeles"]})
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "x"},
        "US-LA 洛杉矶 01": {"type": "Vmess"},
        "US Plain 02": {"type": "Vmess"},
    }
    g = c.get_all_nodes_by_group(proxies)
    assert g["US/Los Angeles"] == ["US-LA 洛杉矶 01"]
    assert g["US/_other"] == ["US Plain 02"]


def test_exit_label_from_ipwhois_parses_country_and_operator():
    from net_auto_switch.clash import exit_label_from_ipwhois

    country, operator = exit_label_from_ipwhois(
        {"isp": "DigitalOcean LLC", "org": "", "country_code": "SG"}
    )
    assert country == "SG"
    assert operator == "DigitalOcean"


def test_exit_label_from_ipwhois_falls_back_to_isp():
    from net_auto_switch.clash import exit_label_from_ipwhois

    country, operator = exit_label_from_ipwhois(
        {"isp": "Acme Telecom", "org": "", "country_code": "JP"}
    )
    assert country == "JP" and operator == "Acme Telecom"


def test_probe_exit_retries_then_succeeds(monkeypatch):
    import net_auto_switch.clash as clash_mod

    c = make_ctrl()
    monkeypatch.setattr(c, "switch_proxy", lambda *a, **k: True)
    monkeypatch.setattr(clash_mod.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    class _R:
        def json(self):
            return {"isp": "DigitalOcean", "org": "", "country_code": "SG"}

    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("ssl eof")
        return _R()

    monkeypatch.setattr(clash_mod.requests, "get", fake_get)
    country, operator = c.probe_exit("node", "GLOBAL")
    assert country == "SG" and operator == "DigitalOcean"
    assert calls["n"] == 2  # retried after the first failure


def test_probe_exit_gives_up_returns_empty(monkeypatch):
    import net_auto_switch.clash as clash_mod

    c = make_ctrl()
    monkeypatch.setattr(c, "switch_proxy", lambda *a, **k: True)
    monkeypatch.setattr(clash_mod.time, "sleep", lambda *_: None)

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(clash_mod.requests, "get", boom)
    assert c.probe_exit("node", "GLOBAL", retries=2) == ("", "")


def test_is_tun_enabled(monkeypatch):
    import net_auto_switch.clash as clash_mod

    c = make_ctrl()

    class _R:
        def json(self):
            return {"tun": {"enable": True, "stack": "gVisor"}, "mode": "rule"}

    monkeypatch.setattr(clash_mod.requests, "get", lambda *a, **k: _R())
    assert c.is_tun_enabled() is True


def test_is_tun_enabled_false_on_error(monkeypatch):
    import net_auto_switch.clash as clash_mod

    def boom(*a, **k):
        raise OSError("down")

    c = make_ctrl()
    monkeypatch.setattr(clash_mod.requests, "get", boom)
    assert c.is_tun_enabled() is False


# ----- blacklist exclusion -----


def test_name_blacklist_excludes_cn_hk():
    c = make_ctrl(priority=["JP", "CN", "HK"], blacklist={"countries": ["CN", "HK"]})
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "x"},
        "JP-1 日本": {"type": "Vmess"},
        "CN-1 中国": {"type": "Vmess"},
        "HK-1 香港": {"type": "Vmess"},
    }
    g = c.get_all_nodes_by_group(proxies)
    assert g.get("JP") == ["JP-1 日本"]
    assert "CN" not in g and "HK" not in g  # blacklisted countries excluded


def test_learned_blacklist_excludes(tmp_path):
    c = make_ctrl(priority=["JP"], blacklist={"countries": []}, state_dir=str(tmp_path))
    from net_auto_switch import blacklist as bl

    bl.record_learned(str(tmp_path / "blacklist.json"), "JP-bad 日本", now=1e9)
    c._reload_learned(now=1e9)  # test hook to reload after writing the file
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "x"},
        "JP-bad 日本": {"type": "Vmess"},
        "JP-ok 日本": {"type": "Vmess"},
    }
    g = c.get_all_nodes_by_group(proxies)
    assert g["JP"] == ["JP-ok 日本"]


def test_entry_blacklist_excludes_chinese_cloud(monkeypatch):
    c = make_ctrl(priority=["JP"], blacklist={"countries": [], "operators": ["腾讯云"]})
    # node JP-1 server resolves to a Tencent-cloud entry
    monkeypatch.setattr(
        c,
        "_server_of",
        lambda name: "relay.qcloud.com" if name == "JP-1 日本" else "",
    )
    monkeypatch.setattr(
        c,
        "_entry_info",
        lambda server: ("CN", "腾讯云 Tencent Cloud") if server else ("", ""),
    )
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "x"},
        "JP-1 日本": {"type": "Vmess"},
        "JP-2 日本": {"type": "Vmess"},
    }
    g = c.get_all_nodes_by_group(proxies)
    assert g["JP"] == ["JP-2 日本"]  # JP-1 excluded by entry operator


def test_entry_blacklist_excludes_cn_country(monkeypatch):
    c = make_ctrl(priority=["JP"], blacklist={"countries": ["CN"], "operators": []})
    monkeypatch.setattr(c, "_server_of", lambda name: "relay" if name == "JP-1 日本" else "")
    monkeypatch.setattr(
        c,
        "_entry_info",
        lambda server: ("CN", "Some ISP") if server else ("", ""),
    )
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "x"},
        "JP-1 日本": {"type": "Vmess"},
        "JP-2 日本": {"type": "Vmess"},
    }
    g = c.get_all_nodes_by_group(proxies)
    assert g["JP"] == ["JP-2 日本"]  # JP-1 excluded by entry country CN


def test_run_cycle_learns_bad_exit_and_picks_next(tmp_path, monkeypatch):
    c = make_ctrl(priority=["JP"], blacklist={"countries": ["CN"]}, state_dir=str(tmp_path))
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "stale"},
        "stale": {"type": "Vmess"},
        "JP-a 日本": {"type": "Vmess"},
        "JP-b 日本": {"type": "Vmess"},
    }
    monkeypatch.setattr(c, "get_proxies", lambda: proxies)
    monkeypatch.setattr(c, "get_mode", lambda: "global")
    monkeypatch.setattr(c, "test_all_delays", lambda n: {x: 50 for x in n})
    monkeypatch.setattr(c, "test_delay", lambda n: 9999)
    switched = []
    monkeypatch.setattr(c, "switch_proxy", lambda node, group: switched.append(node) or True)
    # first landed node exits in CN (bad), second is clean
    exits = {"JP-a 日本": ("CN", "x"), "JP-b 日本": ("JP", "ok")}
    monkeypatch.setattr(c, "query_exit", lambda: exits[switched[-1]])
    c.run_cycle(dry_run=False)
    assert switched[-1] == "JP-b 日本"  # moved off the CN-exit node
    from net_auto_switch import blacklist as bl

    assert "JP-a 日本" in bl.load_learned(str(tmp_path / "blacklist.json"), 7, 1e9)
