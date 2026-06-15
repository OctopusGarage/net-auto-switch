from unittest import mock

from net_auto_switch import notify


def test_send_builds_osascript_with_title_and_subtitle():
    with mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("Title", "Body", "Sub")
    cmd = run.call_args[0][0]
    assert cmd[0] == "osascript"
    script = cmd[2]
    assert 'display notification "Body"' in script
    assert 'with title "Title"' in script
    assert 'subtitle "Sub"' in script


def test_send_omits_subtitle_when_empty():
    with mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("T", "B")
    assert "subtitle" not in run.call_args[0][0][2]


def test_send_escapes_quotes():
    with mock.patch("net_auto_switch.notify.subprocess.run") as run:
        notify.send("T", 'a "quoted" node')
    assert r"a \"quoted\" node" in run.call_args[0][0][2]


def test_send_swallows_errors():
    with mock.patch("net_auto_switch.notify.subprocess.run", side_effect=OSError("boom")):
        notify.send("T", "B")  # must not raise
