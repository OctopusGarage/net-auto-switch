"""Best-effort desktop notifications (no extra deps).

macOS uses osascript (the same AppleScript mechanism used for profile switching),
Linux uses notify-send when available. Other platforms are a no-op. Failures are
always swallowed — a missing banner must never disturb the daemon's switching logic.
"""

import logging
import subprocess
import sys

log = logging.getLogger("net_auto_switch.notify")


def _quote(s: str) -> str:
    """Escape a Python string for embedding in an AppleScript double-quoted literal."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def send(title: str, message: str, subtitle: str = "") -> None:
    """Show a desktop notification. Best-effort: never raises."""
    try:
        if sys.platform == "darwin":
            script = f"display notification {_quote(message)} with title {_quote(title)}"
            if subtitle:
                script += f" subtitle {_quote(subtitle)}"
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        elif sys.platform.startswith("linux"):
            body = f"{subtitle}\n{message}" if subtitle else message
            subprocess.run(["notify-send", title, body], capture_output=True, timeout=10)
        # Other platforms (Windows, …): no desktop-notification backend wired up.
    except Exception as e:
        log.warning(f"Notification failed: {e}")
