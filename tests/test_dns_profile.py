import textwrap

import pytest
import yaml

from net_auto_switch.config import ConfigError
from net_auto_switch.dns_profile import load_dns_profile, render_dns_profile


def _config(tmp_path, dns_table):
    path = tmp_path / "config.toml"
    path.write_text(textwrap.dedent(dns_table), encoding="utf-8")
    return str(path)


def test_render_routes_cn_and_video_to_domestic_upstream(tmp_path):
    path = _config(
        tmp_path,
        """
        [dns]
        domestic_upstreams = ["https://cn.example/dns-query"]
        video_domains = ["bilibili.com", "v.qq.com"]
        """,
    )
    result = yaml.safe_load(render_dns_profile(load_dns_profile(path)))

    assert result == {
        "tcp-concurrent": True,
        "dns": {
            "enable": True,
            "cache-algorithm": "arc",
            "nameserver-policy": {
                "geosite:cn": ["https://cn.example/dns-query"],
                "+.bilibili.com": ["https://cn.example/dns-query"],
                "+.v.qq.com": ["https://cn.example/dns-query"],
            },
            "nameserver": [
                "https://dns.google/dns-query",
                "https://cloudflare-dns.com/dns-query",
            ],
        },
    }


def test_render_uses_custom_global_upstreams_and_geosite(tmp_path):
    path = _config(
        tmp_path,
        """
        [dns]
        domestic_upstreams = ["223.5.5.5"]
        global_upstreams = ["https://resolver.example/dns-query"]
        domestic_geosite = "cn-custom"
        """,
    )
    result = yaml.safe_load(render_dns_profile(load_dns_profile(path)))
    assert result["dns"]["nameserver-policy"] == {"geosite:cn-custom": ["223.5.5.5"]}
    assert result["dns"]["nameserver"] == ["https://resolver.example/dns-query"]


@pytest.mark.parametrize(
    ("dns_table", "message"),
    [
        ("[clash]\nsecret = 'x'\n", "[dns]"),
        ("[dns]\ndomestic_upstreams = []\n", "domestic_upstreams"),
        (
            "[dns]\ndomestic_upstreams = ['https://cn.example/dns-query']\n"
            "global_upstreams = ['http://dns.example/dns-query']\n",
            "global_upstreams",
        ),
        (
            "[dns]\ndomestic_upstreams = ['https://cn.example/dns-query']\n"
            "video_domains = ['bad/domain']\n",
            "video_domains",
        ),
        (
            "[dns]\ndomestic_upstreams = ['https://cn.example/dns-query']\n"
            "domestic_geosite = 'bad:name'\n",
            "domestic_geosite",
        ),
        (
            "[dns]\ndomestic_upstreams = ['https://cn.example/dns-query']\n"
            "domesitc_geosite = 'cn'\n",
            "domesitc_geosite",
        ),
    ],
)
def test_invalid_dns_profile_raises_clear_error(tmp_path, dns_table, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[")):
        load_dns_profile(_config(tmp_path, dns_table))
