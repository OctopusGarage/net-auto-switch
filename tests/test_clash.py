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
        "jp1": {"type": "Shadowsocks"},   # name "jp1" -> JP_Other (no Tokyo by name)
    }
    with mock.patch.object(c, "get_proxies", return_value=proxies), \
         mock.patch.object(c, "test_all_delays", return_value={"jp1": 100}), \
         mock.patch.object(c, "enrich_tokyo_via_ip") as enrich, \
         mock.patch.object(c, "switch_proxy") as switch, \
         mock.patch.object(c, "get_node_region") as region:
        result = c.run_cycle(dry_run=True)
    enrich.assert_not_called()
    region.assert_not_called()
    switch.assert_not_called()
    assert result is False


def test_run_cycle_non_dry_run_enriches_when_no_tokyo():
    c = make_ctrl()
    proxies = {
        "GLOBAL": {"type": "Selector", "now": "jp1"},
        "jp1": {"type": "Shadowsocks"},
    }
    with mock.patch.object(c, "get_proxies", return_value=proxies), \
         mock.patch.object(c, "test_all_delays", return_value={"jp1": 100}), \
         mock.patch.object(c, "enrich_tokyo_via_ip") as enrich, \
         mock.patch.object(c, "switch_proxy"):
        c.run_cycle(dry_run=False)
    enrich.assert_called_once()
