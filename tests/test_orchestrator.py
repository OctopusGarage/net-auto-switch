from unittest import mock

from net_auto_switch.config import ClashConfig, Config, WifiConfig
from net_auto_switch.orchestrator import Orchestrator


def make_orch(**wifi_kw):
    cfg = Config(
        main_interval=600,
        wifi=WifiConfig(**wifi_kw),
        clash=ClashConfig(secret="x"),
    )
    return Orchestrator(cfg)


def test_wifi_due_first_time():
    o = make_orch(check_interval=3600)
    assert o._wifi_due(now=1000.0, last_check=0.0) is True


def test_wifi_not_due_within_interval():
    o = make_orch(check_interval=3600)
    assert o._wifi_due(now=1000.0, last_check=999.0) is False


def test_cooldown_ok_after_period():
    o = make_orch(switch_cooldown=7200)
    assert o._cooldown_ok(now=8000.0, last_switch=0.0) is True


def test_cooldown_blocks_within_period():
    o = make_orch(switch_cooldown=7200)
    assert o._cooldown_ok(now=100.0, last_switch=0.0) is False


def test_run_once_skips_wifi_when_disabled():
    o = make_orch(enabled=False)
    with mock.patch.object(o, "_maybe_wifi") as wifi_step, \
         mock.patch.object(o.clash, "run_cycle", return_value=False) as clash_step:
        o.run_once(now=1000.0)
    wifi_step.assert_not_called()
    clash_step.assert_called_once()


def test_run_once_runs_wifi_then_clash_when_enabled():
    o = make_orch(enabled=True)
    with mock.patch.object(o, "_maybe_wifi") as wifi_step, \
         mock.patch.object(o.clash, "run_cycle", return_value=False) as clash_step:
        o.run_once(now=1000.0)
    wifi_step.assert_called_once()
    clash_step.assert_called_once()


def test_wifi_failure_does_not_block_clash():
    o = make_orch(enabled=True)
    with mock.patch.object(o, "_maybe_wifi", side_effect=RuntimeError("boom")), \
         mock.patch.object(o.clash, "run_cycle", return_value=False) as clash_step:
        o.run_once(now=1000.0)  # must not raise
    clash_step.assert_called_once()


def test_clash_failure_is_swallowed():
    o = make_orch(enabled=True)
    with mock.patch.object(o, "_maybe_wifi") as wifi_step, \
         mock.patch.object(o.clash, "run_cycle", side_effect=RuntimeError("boom")):
        o.run_once(now=1000.0)  # must not raise
    wifi_step.assert_called_once()


def test_run_once_logs_cycle_header():
    o = make_orch(enabled=True)
    with mock.patch.object(o, "_maybe_wifi"), \
         mock.patch.object(o.clash, "run_cycle", return_value=False), \
         mock.patch("net_auto_switch.orchestrator.log") as log:
        o.run_once(now=1000.0)
    headers = [c.args[0] for c in log.info.call_args_list if c.args]
    assert any("cycle start" in h for h in headers)


def test_run_once_dry_run_header_marked():
    cfg = Config(main_interval=600, wifi=WifiConfig(enabled=True), clash=ClashConfig(secret="x"))
    o = Orchestrator(cfg, dry_run=True)
    with mock.patch.object(o, "_maybe_wifi"), \
         mock.patch.object(o.clash, "run_cycle", return_value=False), \
         mock.patch("net_auto_switch.orchestrator.log") as log:
        o.run_once(now=1000.0)
    headers = [c.args[0] for c in log.info.call_args_list if c.args]
    assert any("dry-run" in h for h in headers)


def test_run_once_logs_traceback_on_wifi_error():
    o = make_orch(enabled=True)
    with mock.patch.object(o, "_maybe_wifi", side_effect=RuntimeError("boom")), \
         mock.patch.object(o.clash, "run_cycle", return_value=False), \
         mock.patch("net_auto_switch.orchestrator.log") as log:
        o.run_once(now=1000.0)
    log.exception.assert_called_once()


def test_run_once_logs_traceback_on_clash_error():
    o = make_orch(enabled=True)
    with mock.patch.object(o, "_maybe_wifi"), \
         mock.patch.object(o.clash, "run_cycle", side_effect=RuntimeError("boom")), \
         mock.patch("net_auto_switch.orchestrator.log") as log:
        o.run_once(now=1000.0)
    log.exception.assert_called_once()
