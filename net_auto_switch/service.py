"""Install net-auto-switch as a native background service, per platform.

- macOS   -> launchd LaunchAgent (long-running daemon; via scripts/install-launchd.sh)
- Linux   -> systemd --user service (long-running daemon, Restart=always, lingered)
- Windows -> Task Scheduler task running `--once` every `main_interval` minutes

The render_* helpers are pure (unit-testable); the install/uninstall/status entry
points shell out to the platform's native tool.
"""

import logging
import os
import subprocess
import sys

log = logging.getLogger("net_auto_switch.service")

LAUNCHD_LABEL = "com.octopusgarage.net-auto-switch"
SERVICE_NAME = "net-auto-switch"


def venv_python(project_dir):
    """Path to the uv-managed venv interpreter for this install. Each branch matches
    the OS it actually runs on, and uses explicit separators so the path is stable
    regardless of where (which OS) the code is exercised."""
    if os.name == "nt":
        return os.path.join(project_dir, ".venv", "Scripts", "python.exe")
    return f"{project_dir}/.venv/bin/python"


# ----- Linux: systemd --user -----
def render_systemd_unit(python, project_dir, config_path):
    return (
        "[Unit]\n"
        "Description=net-auto-switch (layered WiFi + Clash Verge auto-switch)\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={project_dir}\n"
        f"ExecStart={python} -m net_auto_switch.cli --config {config_path}\n"
        "Restart=always\n"
        "RestartSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemd_unit_path():
    base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "systemd", "user", f"{SERVICE_NAME}.service")


# ----- Windows: Task Scheduler -----
def render_schtasks_command(python, config_path):
    """The /TR program string: run one switch cycle, then exit."""
    return f'"{python}" -m net_auto_switch.cli --once --config "{config_path}"'


# ----- dispatch -----
def install(project_dir, config_path, interval_minutes=10):
    if sys.platform == "darwin":
        return _install_launchd(project_dir)
    if sys.platform.startswith("linux"):
        return _install_systemd(project_dir, config_path)
    if os.name == "nt":
        return _install_schtasks(project_dir, config_path, interval_minutes)
    log.error(f"Unsupported platform for service install: {sys.platform}")
    return False


def uninstall():
    if sys.platform == "darwin":
        return _run(["launchctl", "unload", _launchd_plist()]) and _rm(_launchd_plist())
    if sys.platform.startswith("linux"):
        _run(["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.service"])
        return _rm(_systemd_unit_path()) and _run(["systemctl", "--user", "daemon-reload"])
    if os.name == "nt":
        return _run(["schtasks", "/Delete", "/TN", SERVICE_NAME, "/F"])
    return False


def status():
    if sys.platform == "darwin":
        return _run(["launchctl", "list", LAUNCHD_LABEL])
    if sys.platform.startswith("linux"):
        return _run(["systemctl", "--user", "status", f"{SERVICE_NAME}.service", "--no-pager"])
    if os.name == "nt":
        return _run(["schtasks", "/Query", "/TN", SERVICE_NAME])
    return False


# ----- platform installers -----
def _launchd_plist():
    return os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")


def _install_launchd(project_dir):
    # Reuse the existing, battle-tested macOS installer.
    script = os.path.join(project_dir, "scripts", "install-launchd.sh")
    return _run(["bash", script])


def _install_systemd(project_dir, config_path):
    python = venv_python(project_dir)
    unit_path = _systemd_unit_path()
    os.makedirs(os.path.dirname(unit_path), exist_ok=True)
    with open(unit_path, "w", encoding="utf-8") as f:
        f.write(render_systemd_unit(python, project_dir, config_path))
    log.info(f"Wrote {unit_path}")
    ok = _run(["systemctl", "--user", "daemon-reload"])
    ok = _run(["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.service"]) and ok
    # Let the user service keep running without an active login session.
    _run(["loginctl", "enable-linger", os.environ.get("USER", "")])
    return ok


def _install_schtasks(project_dir, config_path, interval_minutes):
    python = venv_python(project_dir)
    tr = render_schtasks_command(python, config_path)
    return _run(
        [
            "schtasks",
            "/Create",
            "/TN",
            SERVICE_NAME,
            "/TR",
            tr,
            "/SC",
            "MINUTE",
            "/MO",
            str(max(1, int(interval_minutes))),
            "/F",
        ]
    )


# ----- small I/O helpers -----
def _run(cmd):
    try:
        return subprocess.run(cmd, check=False).returncode == 0
    except FileNotFoundError as e:
        log.error(f"Required tool not found: {e}")
        return False


def _rm(path):
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except OSError as e:
        log.error(f"Could not remove {path}: {e}")
        return False
