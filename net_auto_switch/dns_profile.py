"""Render an opt-in Mihomo DNS merge without changing the running daemon."""

import ipaddress
import re
import tomllib
from urllib.parse import urlsplit

import yaml

from .config import ConfigError, _resolve_path

GLOBAL_UPSTREAMS = [
    "https://dns.google/dns-query",
    "https://cloudflare-dns.com/dns-query",
]
_DNS_KEYS = {"domestic_upstreams", "global_upstreams", "video_domains", "domestic_geosite"}
_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_GEOSITE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _https_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not any(char.isspace() for char in value)
        and parsed.username is None
        and parsed.password is None
        and (port is None or 0 < port < 65536)
        and not parsed.fragment
    )


def _upstream(value, allow_ip):
    if not isinstance(value, str) or not value:
        return False
    if _https_url(value):
        return True
    if allow_ip:
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            pass
    return False


def _upstream_list(data, key, *, allow_ip):
    values = data.get(key)
    if (
        not isinstance(values, list)
        or not values
        or any(not _upstream(value, allow_ip) for value in values)
    ):
        kind = "HTTPS DoH URLs or IP addresses" if allow_ip else "HTTPS DoH URLs"
        raise ConfigError(f"dns.{key} must be a nonempty list of {kind}")
    return values


def _domain(value):
    return (
        isinstance(value, str)
        and len(value) <= 253
        and "." in value
        and all(_DOMAIN_LABEL.fullmatch(label) for label in value.lower().split("."))
    )


def load_dns_profile(path=None):
    """Read and validate only `[dns]`; existing daemon configuration stays separate."""
    resolved = _resolve_path(path)
    if not resolved:
        raise ConfigError("No config file found for DNS rendering")
    try:
        with open(resolved, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML: {e}") from e

    dns = data.get("dns")
    if not isinstance(dns, dict):
        raise ConfigError("Add a [dns] table to config.toml before rendering")
    unknown = set(dns) - _DNS_KEYS
    if unknown:
        raise ConfigError(f"Unknown [dns] key: {sorted(unknown)[0]}")

    domestic = _upstream_list(dns, "domestic_upstreams", allow_ip=True)
    global_upstreams = _upstream_list(
        {"global_upstreams": dns.get("global_upstreams", GLOBAL_UPSTREAMS)},
        "global_upstreams",
        allow_ip=False,
    )
    video_domains = dns.get("video_domains", [])
    if not isinstance(video_domains, list) or any(not _domain(v) for v in video_domains):
        raise ConfigError("dns.video_domains must be a list of domain suffixes")
    geosite = dns.get("domestic_geosite", "cn")
    if not isinstance(geosite, str) or not _GEOSITE.fullmatch(geosite):
        raise ConfigError("dns.domestic_geosite must be a simple geosite name")

    return {
        "domestic_upstreams": domestic,
        "global_upstreams": global_upstreams,
        "video_domains": video_domains,
        "domestic_geosite": geosite,
    }


def render_dns_profile(profile):
    """Return a complete Global Extension Merge YAML for Clash Verge."""
    domestic = profile["domestic_upstreams"]
    policy = {f"geosite:{profile['domestic_geosite']}": list(domestic)}
    for domain in profile["video_domains"]:
        policy[f"+.{domain.lower()}"] = list(domestic)
    return yaml.safe_dump(
        {
            "tcp-concurrent": True,
            "dns": {
                "enable": True,
                "cache-algorithm": "arc",
                "nameserver-policy": policy,
                "nameserver": profile["global_upstreams"],
            },
        },
        sort_keys=False,
        allow_unicode=True,
    )
