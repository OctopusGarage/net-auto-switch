from net_auto_switch import whois
from net_auto_switch.geo import by_whois


def test_country_of_server_maps_known(monkeypatch):
    monkeypatch.setattr(
        whois,
        "lookup",
        lambda *a, **k: [whois.LookupResult(target="x", ip="1.1.1.1", operator="o", country="JP")],
    )
    assert by_whois.country_of_server("relay.example.com", {"JP", "SG"}) == "JP"


def test_country_of_server_unknown_returns_none(monkeypatch):
    monkeypatch.setattr(
        whois,
        "lookup",
        lambda *a, **k: [whois.LookupResult(target="x", ip="1.1.1.1", operator="o", country="ZZ")],
    )
    assert by_whois.country_of_server("relay.example.com", {"JP", "SG"}) is None


def test_country_of_server_no_result(monkeypatch):
    monkeypatch.setattr(whois, "lookup", lambda *a, **k: [])
    assert by_whois.country_of_server("relay.example.com", {"JP"}) is None
