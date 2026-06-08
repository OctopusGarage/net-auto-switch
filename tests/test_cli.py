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
