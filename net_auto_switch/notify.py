"""Best-effort macOS desktop notifications via osascript (no extra deps).

Uses the same AppleScript mechanism the project already relies on for profile
switching. Failures are swallowed — a missing banner must never disturb the
daemon's switching logic.
"""

import logging
import subprocess

log = logging.getLogger("net_auto_switch.notify")


def _quote(s: str) -> str:
    """Escape a Python string for embedding in an AppleScript double-quoted literal."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def send(title: str, message: str, subtitle: str = "") -> None:
    """Show a macOS notification banner. Best-effort: never raises."""
    script = f"display notification {_quote(message)} with title {_quote(title)}"
    if subtitle:
        script += f" subtitle {_quote(subtitle)}"
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except Exception as e:
        log.warning(f"Notification failed: {e}")
