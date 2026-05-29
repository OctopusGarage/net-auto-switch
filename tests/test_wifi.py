from unittest import mock

from net_auto_switch import wifi


def test_is_bad_network_none_is_bad():
    assert wifi.is_bad_network(None, None, bad_latency=200, bad_loss=5) is True


def test_is_bad_network_high_latency():
    assert wifi.is_bad_network(250, 0, bad_latency=200, bad_loss=5) is True


def test_is_bad_network_high_loss():
    assert wifi.is_bad_network(50, 10, bad_latency=200, bad_loss=5) is True


def test_is_bad_network_good():
    assert wifi.is_bad_network(50, 0, bad_latency=200, bad_loss=5) is False


def test_candidate_wifis_intersection():
    with mock.patch.object(wifi, "known_wifis", return_value=["A", "B", "C"]), \
         mock.patch.object(wifi, "available_wifis", return_value={"B", "C", "D"}):
        result = set(wifi.candidate_wifis("en0"))
    assert result == {"B", "C"}


def test_ping_host_parses_output():
    fake = mock.Mock()
    fake.stdout = (
        "3 packets transmitted, 3 packets received, 0.0% packet loss\n"
        "round-trip min/avg/max/stddev = 58.4/63.2/68.1/4.8 ms\n"
    )
    with mock.patch("subprocess.run", return_value=fake):
        lat, loss = wifi.ping_host()
    assert lat == 63.2
    assert loss == 0.0


def test_switch_to_dry_run_does_not_call_subprocess():
    with mock.patch("subprocess.run") as m:
        ok = wifi.switch_to("MyWifi", interface="en0", dry_run=True)
    m.assert_not_called()
    assert ok is True


def test_find_best_wifi_picks_lowest_latency():
    # ping_host is called once per candidate; return varied latencies in order
    results = [(120.0, 0.0), (40.0, 0.0), (None, None)]
    with mock.patch.object(wifi, "ping_host", side_effect=results):
        name, lat = wifi.find_best_wifi(["A", "B", "C"])
    assert name == "B"
    assert lat == 40.0


def test_find_best_wifi_all_unreachable():
    with mock.patch.object(wifi, "ping_host", side_effect=[(None, None), (None, None)]):
        name, lat = wifi.find_best_wifi(["A", "B"])
    assert name is None
    assert lat is None
