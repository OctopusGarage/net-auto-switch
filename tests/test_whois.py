from net_auto_switch import whois


def test_is_ip():
    assert whois.is_ip("1.1.1.1")
    assert whois.is_ip("2606:4700:4700::1111")
    assert not whois.is_ip("example.com")
    assert not whois.is_ip("")


def test_match_operator_by_hint():
    assert whois.match_operator("OrgName: Amazon amazonaws.com") == "AWS"
    assert whois.match_operator("route via qcloud backbone") == "腾讯云 Tencent Cloud"
    assert whois.match_operator("Vultr Holdings, LLC") == "Vultr"


def test_match_operator_no_match():
    assert whois.match_operator("some tiny local isp ltd") is None


def test_extract_field_skips_registry_noise():
    raw = "netname:        APNIC-AP\norganisation:   Tencent Cloud Computing"
    # netname value contains 'apnic' noise -> skipped; org-name picked instead
    assert whois.extract_field(raw, "netname") is None
    assert whois.extract_field(raw, "organisation") == "Tencent Cloud Computing"


def test_extract_field_ignores_comment_lines():
    raw = "% this is a comment netname: x\nnetname: RealNet"
    assert whois.extract_field(raw, "netname") == "RealNet"


def test_guess_operator_prefers_hint_over_fallback():
    raw = "netname: SOMENET\ndescr: powered by amazonaws.com infra"
    assert whois.guess_operator(raw) == "AWS"


def test_guess_operator_falls_back_to_field():
    raw = "owner: Tiny Local Telecom"
    assert whois.guess_operator(raw) == "Tiny Local Telecom"


def test_guess_operator_unknown():
    assert whois.guess_operator("nothing useful here") == "未知"
