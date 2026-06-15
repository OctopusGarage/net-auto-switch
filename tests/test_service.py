from unittest import mock

from net_auto_switch import service


def test_venv_python_posix():
    with mock.patch("net_auto_switch.service.os.name", "posix"):
        assert service.venv_python("/opt/nas").endswith("/.venv/bin/python")


def test_venv_python_windows():
    with mock.patch("net_auto_switch.service.os.name", "nt"):
        p = service.venv_python(r"C:\nas")
        assert p.endswith("python.exe")
        assert ".venv" in p and "Scripts" in p


def test_render_systemd_unit():
    py = "/opt/nas/.venv/bin/python"
    unit = service.render_systemd_unit(py, "/opt/nas", "/opt/nas/config.toml")
    assert f"ExecStart={py} -m net_auto_switch.cli --config /opt/nas/config.toml" in unit
    assert "Restart=always" in unit
    assert "WorkingDirectory=/opt/nas" in unit
    assert "WantedBy=default.target" in unit


def test_render_schtasks_command_quotes_paths():
    cmd = service.render_schtasks_command(r"C:\nas\.venv\Scripts\python.exe", r"C:\nas\config.toml")
    assert cmd.startswith('"C:\\nas\\.venv\\Scripts\\python.exe" -m net_auto_switch.cli --once')
    assert '--config "C:\\nas\\config.toml"' in cmd


def test_install_dispatch_linux_writes_unit_and_enables(tmp_path):
    unit = tmp_path / "net-auto-switch.service"
    calls = []
    with (
        mock.patch("net_auto_switch.service.sys.platform", "linux"),
        mock.patch("net_auto_switch.service._systemd_unit_path", return_value=str(unit)),
        mock.patch("net_auto_switch.service.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        calls = run
        ok = service.install("/opt/nas", "/opt/nas/config.toml")
    assert ok
    assert unit.exists()
    assert "ExecStart=" in unit.read_text()
    cmds = [c.args[0] for c in calls.call_args_list]
    assert ["systemctl", "--user", "daemon-reload"] in cmds
    assert any(c[:3] == ["systemctl", "--user", "enable"] for c in cmds)


def test_install_dispatch_windows_uses_schtasks():
    with (
        mock.patch("net_auto_switch.service.sys.platform", "win32"),
        mock.patch("net_auto_switch.service.os.name", "nt"),
        mock.patch("net_auto_switch.service.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        ok = service.install(r"C:\nas", r"C:\nas\config.toml", interval_minutes=10)
    assert ok
    cmd = run.call_args[0][0]
    assert cmd[0] == "schtasks" and "/Create" in cmd
    assert "MINUTE" in cmd and "10" in cmd


def test_install_dispatch_macos_runs_launchd_script():
    with (
        mock.patch("net_auto_switch.service.sys.platform", "darwin"),
        mock.patch("net_auto_switch.service.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        ok = service.install("/opt/nas", "/opt/nas/config.toml")
    assert ok
    cmd = run.call_args[0][0]
    assert cmd[0] == "bash" and cmd[1].endswith("scripts/install-launchd.sh")
