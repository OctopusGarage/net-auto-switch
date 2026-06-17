import json

from net_auto_switch import blacklist as bl


def test_operator_blacklisted_substring_ci():
    assert bl.operator_blacklisted("腾讯云 Tencent Cloud", ["腾讯云"]) is True
    assert bl.operator_blacklisted("aliyun.com", ["阿里云", "aliyun"]) is True
    assert bl.operator_blacklisted("AWS", ["腾讯云", "阿里云"]) is False
    assert bl.operator_blacklisted("", ["腾讯云"]) is False


def test_country_blacklisted():
    assert bl.country_blacklisted("CN", ["CN", "HK"]) is True
    assert bl.country_blacklisted("hk", ["CN", "HK"]) is True  # case-insensitive
    assert bl.country_blacklisted("JP", ["CN", "HK"]) is False
    assert bl.country_blacklisted(None, ["CN"]) is False


def test_learned_load_record_and_expiry(tmp_path):
    p = str(tmp_path / "blacklist.json")
    bl.record_learned(p, "JP-bad", now=1000.0)
    assert bl.load_learned(p, relearn_days=7, now=1000.0) == {"JP-bad"}
    # 8 days later -> expired
    later = 1000.0 + 8 * 86400
    assert bl.load_learned(p, relearn_days=7, now=later) == set()
    # recording prunes expired entries on write
    bl.record_learned(p, "JP-fresh", now=later)
    data = json.load(open(p))
    assert "JP-bad" not in data and "JP-fresh" in data
