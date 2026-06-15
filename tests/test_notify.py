from unittest import mock

from net_auto_switch import notify


def _patch_platform(value):
    return mock.patch("net_auto_switch.notify.sys.platform", value)


def test_send_builds_osascript_on_macos():
    with _patch_platform("darwin"), mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("Title", "Body", "Sub")
    cmd = run.call_args[0][0]
    assert cmd[0] == "osascript"
    script = cmd[2]
    assert 'display notification "Body"' in script
    assert 'with title "Title"' in script
    assert 'subtitle "Sub"' in script


def test_send_omits_subtitle_when_empty_on_macos():
    with _patch_platform("darwin"), mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("T", "B")
    assert "subtitle" not in run.call_args[0][0][2]


def test_send_escapes_quotes_on_macos():
    with _patch_platform("darwin"), mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("T", 'a "quoted" node')
    assert r"a \"quoted\" node" in run.call_args[0][0][2]


def test_send_uses_notify_send_on_linux():
    with _patch_platform("linux"), mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("Title", "Body", "Sub")
    cmd = run.call_args[0][0]
    assert cmd[0] == "notify-send"
    assert cmd[1] == "Title"
    assert "Body" in cmd[2] and "Sub" in cmd[2]


def test_send_is_noop_on_other_platforms():
    with _patch_platform("win32"), mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("T", "B")
    run.assert_not_called()


def test_send_swallows_errors():
    with (
        _patch_platform("darwin"),
        mock.patch("net_auto_switch.notify.subprocess.run", side_effect=OSError("boom")),
    ):
        notify.send("T", "B")  # must not raise
