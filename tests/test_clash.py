from unittest import mock

from net_auto_switch.clash import ClashController
from net_auto_switch.config import ClashConfig


def make_ctrl():
    return ClashController(ClashConfig(secret="x"))


def test_classify_sg():
    c = make_ctrl()
    assert c.classify_node("SG-01 新加坡") == "SG"


def test_classify_tokyo():
    c = make_ctrl()
    assert c.classify_node("JP Tokyo 东京 01") == "Tokyo"


def test_classify_jp_other():
    c = make_ctrl()
    assert c.classify_node("Japan Osaka 02") == "JP_Other"


def test_classify_trial_still_classifies_name():
    # classify_node 只做地区判断; 试用过滤在 grouping 阶段
    c = make_ctrl()
    assert c.classify_node("US-01") is None


def test_classify_custom_region_us_first():
    cfg = ClashConfig(
        secret="x",
        regions={"US": r"(US|United States|美国|🇺🇸)", "JP": r"(JP|日本)"},
        group_priority=["US", "JP"],
        ip_enrich={},
    )
    c = ClashController(cfg)
    assert c.classify_node("US-LA-01 美国") == "US"
    assert c.classify_node("JP-Tokyo 日本") == "JP"
    assert c.classify_node("SG-01 新加坡") is None  # SG is no longer a configured region


def test_grouping_with_custom_regions():
    cfg = ClashConfig(secret="x", regions={"US": r"(US|美国)"}, group_priority=["US"], ip_enrich={})
    c = ClashController(cfg)
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "us1"},
        "美国-01": {"type": "Vmess"},
        "JP-01": {"type": "Vmess"},
    }
    assert c.get_all_nodes_by_group(proxies) == {"US": ["美国-01"]}


def test_select_node_stable_no_switch():
    c = make_ctrl()
    groups = {"SG": ["sg1"], "Tokyo": [], "JP_Other": []}
    delays = {"sg1": 100}
    assert c.select_node("sg1", "SG", groups, delays) == (False, None)


def test_select_node_switch_within_current_group():
    c = make_ctrl()
    groups = {"SG": ["sg1", "sg2"], "Tokyo": [], "JP_Other": []}
    delays = {"sg1": 400, "sg2": 120}
    assert c.select_node("sg1", "SG", groups, delays) == (True, "sg2")


def test_select_node_downgrade_to_next_group():
    c = make_ctrl()
    groups = {"SG": ["sg1"], "Tokyo": ["tk1"], "JP_Other": []}
    delays = {"sg1": 9999, "tk1": 150}
    assert c.select_node("sg1", "SG", groups, delays) == (True, "tk1")


def test_select_node_all_dead_no_switch():
    c = make_ctrl()
    groups = {"SG": ["sg1"], "Tokyo": ["tk1"], "JP_Other": []}
    delays = {"sg1": 9999, "tk1": 9999}
    assert c.select_node("sg1", "SG", groups, delays) == (False, None)


def test_select_best_in_group_excludes_timeout():
    c = make_ctrl()
    assert c.select_best_in_group(["a", "b"], {"a": 9999, "b": 300}) == "b"


def test_select_best_in_group_empty():
    c = make_ctrl()
    assert c.select_best_in_group([], {}) is None


def test_grouping_excludes_trial_and_selectors():
    c = make_ctrl()
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "sg1"},
        "sg1": {"type": "Shadowsocks"},
        "试用-jp": {"type": "Shadowsocks"},
        "JP Tokyo 1": {"type": "Vmess"},
    }
    groups = c.get_all_nodes_by_group(proxies)
    assert groups["SG"] == ["sg1"]
    assert groups["Tokyo"] == ["JP Tokyo 1"]
    assert all("试用" not in n for g in groups.values() for n in g)


def test_run_cycle_dry_run_does_not_enrich_or_switch():
    c = make_ctrl()
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "jp1"},
        "jp1": {"type": "Shadowsocks"},  # name "jp1" -> JP_Other (no Tokyo by name)
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="global"),
        mock.patch.object(c, "test_all_delays", return_value={"jp1": 100}),
        mock.patch.object(c, "enrich_via_ip") as enrich,
        mock.patch.object(c, "switch_proxy") as switch,
        mock.patch.object(c, "get_node_region") as region,
    ):
        result = c.run_cycle(dry_run=True)
    enrich.assert_not_called()
    region.assert_not_called()
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
    c = ClashController(ClashConfig(secret="x", ip_enrich={}), notify=True)
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
        mock.patch.object(c, "get_exit_operator", return_value="AWS (US)"),
        mock.patch("net_auto_switch.notify.send") as send,
    ):
        c.run_cycle(dry_run=False)
    send.assert_called_once()
    assert send.call_args[0][1] == "JP Tokyo good"  # message = target node
    assert "AWS (US)" in send.call_args[0][2]  # subtitle carries the operator


def test_run_cycle_does_not_notify_when_disabled():
    c = ClashController(ClashConfig(secret="x", ip_enrich={}))  # notify defaults False
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
        mock.patch.object(c, "get_exit_operator", return_value="AWS (US)"),
        mock.patch("net_auto_switch.notify.send") as send,
    ):
        c.run_cycle(dry_run=False)
    send.assert_not_called()


def test_run_cycle_skips_profile_fallback_on_non_macos():
    # All nodes dead would normally trigger the AppleScript profile fallback; on
    # non-macOS that's skipped and the cycle just returns without touching profiles.
    c = ClashController(ClashConfig(secret="x", ip_enrich={}))
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
        mock.patch.object(c, "get_exit_operator") as op,
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
    c = ClashController(ClashConfig(secret="x", ip_enrich={}))  # auto
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
        mock.patch.object(c, "get_exit_operator", return_value="AWS (US)") as op,
    ):
        c.run_cycle(dry_run=False)
    switch.assert_called_once_with("JP Tokyo good", "Proxy")
    op.assert_called_once()  # exit operator is probed after a real switch


def test_run_cycle_missing_managed_group_skips_without_switching():
    c = ClashController(ClashConfig(secret="x", managed_group="Proxy", ip_enrich={}))
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "jp1"},
        "jp1": {"type": "Vmess"},  # name "jp1" -> JP_Other, so groups are non-empty
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "switch_proxy") as switch,
    ):
        result = c.run_cycle(dry_run=False)
    switch.assert_not_called()
    assert result is False


def test_run_cycle_non_dry_run_enriches_when_no_tokyo():
    c = make_ctrl()
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "jp1"},
        "jp1": {"type": "Shadowsocks"},
    }
    with (
        mock.patch.object(c, "get_proxies", return_value=proxies),
        mock.patch.object(c, "get_mode", return_value="global"),
        mock.patch.object(c, "test_all_delays", return_value={"jp1": 100}),
        mock.patch.object(c, "enrich_via_ip") as enrich,
        mock.patch.object(c, "switch_proxy"),
    ):
        c.run_cycle(dry_run=False)
    enrich.assert_called_once()
