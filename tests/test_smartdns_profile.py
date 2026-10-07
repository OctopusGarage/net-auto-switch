import textwrap

import pytest

from net_auto_switch.config import ConfigError
from net_auto_switch.smartdns_profile import load_smartdns_profile, render_smartdns_profile


def _config(tmp_path, smartdns):
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            """
            [dns]
            domestic_upstreams = ["https://cn.example/dns-query", "223.5.5.5"]
            video_domains = ["bilibili.com", "v.qq.com"]

            [smartdns]
            """
        )
        + textwrap.dedent(smartdns),
        encoding="utf-8",
    )
    return str(path)


def test_render_smartdns_caches_and_routes_domains(tmp_path):
    path = _config(
        tmp_path,
        'domestic_domain_set = "/etc/smartdns/cn.txt"\n'
        'cache_file = "/var/cache/smartdns/net-auto-switch.cache"\n',
    )
    lines = render_smartdns_profile(load_smartdns_profile(path)).splitlines()

    assert "bind 127.0.0.1:6053" in lines
    assert "bind-tcp 127.0.0.1:6053" in lines
    assert "cache-size 32768" in lines
    assert "cache-persist yes" in lines
    assert "cache-file /var/cache/smartdns/net-auto-switch.cache" in lines
    assert "speed-check-mode tcp:443,tcp:80" in lines
    assert "response-mode fastest-ip" in lines
    assert "max-reply-ip-num 1" in lines
    assert "server 223.5.5.5 -bootstrap-dns -exclude-default-group" in lines
    assert "server 1.1.1.1 -bootstrap-dns -exclude-default-group" in lines
    assert "server-https https://dns.google/dns-query" in lines
    assert "server-https https://cloudflare-dns.com/dns-query" in lines
    assert (
        "server-https https://cn.example/dns-query -group domestic -exclude-default-group" in lines
    )
    assert "server 223.5.5.5 -group domestic -exclude-default-group" in lines
    assert "domain-set -name cn -type list -file /etc/smartdns/cn.txt" in lines
    assert "nameserver /domain-set:cn/domestic" in lines
    assert "nameserver /bilibili.com/domestic" in lines
    assert "nameserver /v.qq.com/domestic" in lines


def test_render_smartdns_honors_explicit_options(tmp_path):
    path = _config(
        tmp_path,
        'domestic_domain_set = "/srv/dns/cn.txt"\n'
        'cache_file = "/srv/dns/cache"\n'
        'listen = "0.0.0.0:5353"\n'
        "cache_size = 1024\n"
        'bootstrap_servers = ["9.9.9.9"]\n'
        "speed_ports = [853]\n",
    )
    lines = render_smartdns_profile(load_smartdns_profile(path)).splitlines()
    assert "bind 0.0.0.0:5353" in lines
    assert "cache-size 1024" in lines
    assert "speed-check-mode tcp:853" in lines
    assert "server 9.9.9.9 -bootstrap-dns -exclude-default-group" in lines


def test_cache_size_can_exceed_tcp_port_range(tmp_path):
    path = _config(
        tmp_path,
        'domestic_domain_set = "/srv/dns/cn.txt"\n'
        'cache_file = "/srv/dns/cache"\n'
        "cache_size = 100000\n",
    )
    assert "cache-size 100000" in render_smartdns_profile(load_smartdns_profile(path))


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ("", "domestic_domain_set"),
        ('domestic_domain_set = "cn.txt"\ncache_file = "/tmp/cache"\n', "domestic_domain_set"),
        ('domestic_domain_set = "/tmp/cn.txt"\ncache_file = "cache"\n', "cache_file"),
        (
            'domestic_domain_set = "/tmp/cn.txt"\ncache_file = "/tmp/cache"\n'
            'listen = "127.0.0.1:99999"\n',
            "listen",
        ),
        (
            'domestic_domain_set = "/tmp/cn.txt"\ncache_file = "/tmp/cache"\ncache_size = 0\n',
            "cache_size",
        ),
        (
            'domestic_domain_set = "/tmp/cn.txt"\ncache_file = "/tmp/cache"\n'
            "bootstrap_servers = []\n",
            "bootstrap_servers",
        ),
        (
            'domestic_domain_set = "/tmp/cn.txt"\ncache_file = "/tmp/cache"\nspeed_ports = [0]\n',
            "speed_ports",
        ),
        (
            'domestic_domain_set = "/tmp/cn.txt"\ncache_file = "/tmp/cache"\nunknown_key = "x"\n',
            "unknown_key",
        ),
        (
            'domestic_domain_set = "/tmp/cn\\nmalicious"\ncache_file = "/tmp/cache"\n',
            "domestic_domain_set",
        ),
    ],
)
def test_smartdns_config_rejects_invalid_values(tmp_path, settings, message):
    with pytest.raises(ConfigError, match=message):
        load_smartdns_profile(_config(tmp_path, settings))
