from unittest import mock

import pytest

from net_auto_switch import cli


def test_main_once_calls_run_once():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg) as load,
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        inst = Orch.return_value
        cli.main(["--once", "--config", "x.toml"])
    inst.run_once.assert_called_once()
    inst.run_forever.assert_not_called()
    load.assert_called_once_with("x.toml")


def test_main_continuous_calls_run_forever():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg),
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        inst = Orch.return_value
        cli.main([])
    inst.run_forever.assert_called_once()


def test_main_dry_run_passed_through():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg),
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        cli.main(["--once", "--dry-run"])
    _, kwargs = Orch.call_args
    assert kwargs.get("dry_run") is True


def test_main_config_error_exits_nonzero():
    from net_auto_switch.config import ConfigError

    with (
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "load_config", side_effect=ConfigError("no config")),
        mock.patch.object(cli, "log") as log,
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--once"])
    assert exc.value.code == 1
    Orch.assert_not_called()
    log.error.assert_called_once()


def test_main_logs_startup_context():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg),
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "log") as log,
        mock.patch.object(cli, "Orchestrator"),
    ):
        cli.main(["--once", "--dry-run"])
    messages = [c.args[0] for c in log.info.call_args_list if c.args]
    assert any("Starting net-auto-switch" in m for m in messages)
    assert any("dry_run=True" in m for m in messages)


def test_main_init_dispatches_to_cmd_init():
    with mock.patch.object(cli, "cmd_init", return_value=0) as ci:
        with pytest.raises(SystemExit) as exc:
            cli.main(["init", "--yes"])
    assert exc.value.code == 0
    ci.assert_called_once_with(["--yes"])


def test_cmd_init_writes_valid_config(tmp_path, monkeypatch):
    from net_auto_switch.setup import DetectedClash

    det = DetectedClash(
        api="http://127.0.0.1:9097",
        secret="abc",
        proxy_port=7890,
        profiles_yaml=str(tmp_path / "profiles.yaml"),
    )
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: det)
    monkeypatch.setattr(cli, "probe_api", lambda api, secret: "1.0")
    monkeypatch.setattr(cli, "health_check", lambda api, secret: (5, 10))
    monkeypatch.setattr(cli, "ClashController", mock.Mock())  # node preview is best-effort

    out = tmp_path / "config.toml"
    rc = cli.cmd_init(["--yes", "--no-service", "--config", str(out)])

    assert rc == 0
    cfg = cli.load_config(str(out))
    assert cfg.clash.secret == "abc"
    assert cfg.clash.proxy_port == 7890


def test_cmd_init_missing_verge_returns_nonzero(monkeypatch):
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: None)
    assert cli.cmd_init(["--yes", "--no-service"]) == 1


def test_cmd_init_aborts_when_no_reachable_nodes(tmp_path, monkeypatch):
    from net_auto_switch.setup import DetectedClash

    det = DetectedClash(
        api="http://127.0.0.1:9097", secret="abc", proxy_port=7890, profiles_yaml="p.yaml"
    )
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: det)
    monkeypatch.setattr(cli, "probe_api", lambda api, secret: "1.0")
    monkeypatch.setattr(cli, "health_check", lambda api, secret: (0, 8))  # all nodes down
    monkeypatch.setattr(cli, "_confirm", lambda *a, **k: False)  # decline "continue anyway?"

    out = tmp_path / "config.toml"
    assert cli.cmd_init(["--no-service", "--config", str(out)]) == 1
    assert not out.exists()  # aborted before writing


def test_main_update_dispatches_to_cmd_update():
    with mock.patch.object(cli, "cmd_update", return_value=0) as cu:
        with pytest.raises(SystemExit) as exc:
            cli.main(["update"])
    assert exc.value.code == 0
    cu.assert_called_once_with([])


def test_cmd_update_pull_failure_returns_nonzero(monkeypatch):
    def fake_run(cmd, **kw):
        if cmd[:2] == ["git", "-C"]:
            return mock.Mock(returncode=1)
        return mock.Mock(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.cmd_update([]) == 1


def test_cmd_update_syncs_when_service_absent(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return mock.Mock(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli.os.path, "exists", lambda p: False)  # no launchd plist

    assert cli.cmd_update([]) == 0
    assert ["git", "-C", cli.PROJECT_DIR, "pull", "--ff-only"] in calls
    assert any(c[0] == "uv" and "sync" in c for c in calls)


def test_setup_logging_uses_daily_rotation(tmp_path, monkeypatch):
    import logging
    import logging.handlers

    root = logging.getLogger()
    saved = root.handlers[:]
    logpath = tmp_path / "logs" / "nas.log"
    monkeypatch.setattr(cli, "LOG_PATH", str(logpath))
    try:
        cli._setup_logging()
        rotating = [
            h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert rotating, "expected a TimedRotatingFileHandler on the root logger"
        assert rotating[0].backupCount == cli.LOG_BACKUP_DAYS
        assert rotating[0].when == "MIDNIGHT"
        assert logpath.parent.is_dir()
    finally:
        for h in root.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                h.close()
        root.handlers[:] = saved
