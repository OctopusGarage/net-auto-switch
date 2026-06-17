"""Auto-detect Clash Verge settings and render a ready-to-use config.toml.

The pure functions here (parse / render) are unit-tested; the thin I/O wrappers
(detect / probe) just read files and hit the local API.
"""

import json
import os
from dataclasses import dataclass

import yaml

from .geo import catalog as geo_catalog

# Clash Verge keeps its merged runtime config and profiles here on macOS.
CLASH_VERGE_DIR = os.path.expanduser(
    "~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev"
)
CLASH_VERGE_APP = "/Applications/Clash Verge.app"
RUNTIME_CONFIG = "clash-verge.yaml"
PROFILES_YAML = "profiles.yaml"
CLASH_VERGE_RELEASES = "https://github.com/clash-verge-rev/clash-verge-rev/releases"


def clash_verge_diagnosis(base_dir=CLASH_VERGE_DIR, app_path=CLASH_VERGE_APP):
    """Explain why detect_clash_verge() found nothing, with a next step."""
    if os.path.isdir(base_dir):
        return (
            "Clash Verge's config folder exists but has no clash-verge.yaml yet.\n"
            "  Launch Clash Verge once and import a subscription, then re-run."
        )
    if os.path.exists(app_path):
        return (
            "Clash Verge is installed but hasn't run yet.\n"
            "  Launch it once, import your subscription, then re-run."
        )
    return (
        "Clash Verge Rev doesn't appear to be installed.\n"
        f"  Install it from {CLASH_VERGE_RELEASES}, import your subscription, then re-run.\n"
        "  (This tool targets Clash Verge Rev specifically, not ClashX or other forks.)"
    )


@dataclass
class DetectedClash:
    api: str
    secret: str
    proxy_port: int
    profiles_yaml: str


def parse_verge_runtime(text):
    """Extract api / secret / proxy_port from clash-verge.yaml content. Pure."""
    data = yaml.safe_load(text) or {}

    ec = str(data.get("external-controller", "127.0.0.1:9097")).strip()
    host, _, port = ec.rpartition(":")
    host = host or "127.0.0.1"
    if host in ("0.0.0.0", "::", "[::]"):  # listen-on-all → talk to loopback
        host = "127.0.0.1"
    api = f"http://{host}:{port or '9097'}"

    secret = data.get("secret", "")
    secret = "" if secret is None else str(secret)

    proxy_port = data.get("mixed-port") or data.get("port") or 7890

    return {"api": api, "secret": secret, "proxy_port": int(proxy_port)}


def parse_subscriptions(text):
    """Parse remote subscriptions from profiles.yaml content. Pure. Returns a
    list of {name, update_interval (min), allow_auto_update, expire (unix ts),
    used (bytes), total (bytes)}."""
    data = yaml.safe_load(text) or {}
    subs = []
    for item in data.get("items") or []:
        if item.get("type") != "remote":
            continue
        opt = item.get("option") or {}
        extra = item.get("extra") or {}
        subs.append(
            {
                "name": item.get("name") or item.get("uid") or "?",
                "update_interval": int(opt.get("update_interval") or 0),
                "allow_auto_update": bool(opt.get("allow_auto_update", True)),
                "expire": int(extra.get("expire") or 0),
                "used": int(extra.get("upload") or 0) + int(extra.get("download") or 0),
                "total": int(extra.get("total") or 0),
            }
        )
    return subs


def read_subscriptions(profiles_yaml):
    """Read remote subscriptions from a profiles.yaml path; [] if unreadable."""
    try:
        with open(os.path.expanduser(profiles_yaml), encoding="utf-8") as f:
            return parse_subscriptions(f.read())
    except Exception:
        return []


def detect_clash_verge(base_dir=CLASH_VERGE_DIR):
    """Read Clash Verge's runtime config. Returns None if it isn't there."""
    runtime = os.path.join(base_dir, RUNTIME_CONFIG)
    if not os.path.exists(runtime):
        return None
    with open(runtime, encoding="utf-8") as f:
        parsed = parse_verge_runtime(f.read())
    return DetectedClash(
        api=parsed["api"],
        secret=parsed["secret"],
        proxy_port=parsed["proxy_port"],
        profiles_yaml=os.path.join(base_dir, PROFILES_YAML),
    )


def probe_api(api, secret, timeout=5):
    """Return the running Clash/mihomo version, or raise if unreachable."""
    import requests

    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    r = requests.get(f"{api}/version", headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json().get("version", "unknown")


def health_check(api, secret, group="GLOBAL", timeout_ms=5000):
    """Concurrently delay-test a proxy group via the core API. Returns
    (reachable, total). Raises if the group/endpoint is unavailable."""
    import requests

    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    r = requests.get(
        f"{api}/group/{group}/delay",
        headers=headers,
        params={"url": "http://www.gstatic.com/generate_204", "timeout": timeout_ms},
        timeout=timeout_ms / 1000 + 10,
    )
    r.raise_for_status()
    delays = r.json()
    reachable = sum(1 for v in delays.values() if isinstance(v, int) and v > 0)
    return reachable, len(delays)


_TEMPLATE = """\
main_interval = 600          # main loop interval (s)

[wifi]
enabled = true
check_interval = 3600        # WiFi check interval (s)
switch_cooldown = 7200       # cooldown after a WiFi switch (s)
bad_latency_ms = 200
bad_loss_pct = 5
min_improvement_ms = 100
interface = "en0"

[clash]
api = {api}
secret = {secret}
proxy_port = {proxy_port}
delay_limit = 300            # current-node stability threshold (ms)
max_switch_per_min = 3
max_profile_switch_per_30min = 1
profiles_yaml = {profiles_yaml}
trial = "试用"
priority = {priority}
{cities_block}"""


def detect_regions(node_names, catalog=None):
    """Count node-name matches per country code using the built-in geo catalog.
    Returns {country: count} for matches, sorted by count desc. Pure."""
    catalog = catalog or geo_catalog.COUNTRY_RES
    counts = {}
    for code, cre in catalog.items():
        c = sum(1 for n in node_names if cre.search(n))
        if c:
            counts[code] = c
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def detect_cities(node_names, catalog=None):
    """Count node-name matches per city, grouped by country, using the built-in
    city catalog. Returns {country: {city: count}} — a country appears only if
    ≥1 of its cities is detected; cities sorted by count desc. Pure."""
    catalog = catalog or geo_catalog.CITY_RES  # {city: (country, compiled_regex)}
    by_country = {}
    for city, (country, cre) in catalog.items():
        c = sum(1 for n in node_names if cre.search(n))
        if c:
            by_country.setdefault(country, {})[city] = c
    return {
        country: dict(sorted(cities.items(), key=lambda kv: -kv[1]))
        for country, cities in by_country.items()
    }


def parse_index_order(text, items):
    """Parse a typed list of 1-based indices into `items` (whitespace/comma
    separated) into (ordered_items, invalid_tokens). Order-preserving,
    de-duplicated; out-of-range/non-numeric tokens go to invalid. Empty text →
    ([], []) so the caller can substitute a default. Pure."""
    ordered, invalid, seen = [], [], set()
    for tok in text.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(items):
            item = items[int(tok) - 1]
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        else:
            invalid.append(tok)
    return ordered, invalid


def resolve_priority(text, valid_names):
    """Parse a comma-separated priority string against valid region names.
    Case-insensitive, order-preserving, de-duplicated. Returns
    (resolved_canonical_names, invalid_tokens). Pure."""
    lookup = {v.lower(): v for v in valid_names}
    resolved, invalid, seen = [], [], set()
    for tok in text.split(","):
        t = tok.strip()
        if not t:
            continue
        canon = lookup.get(t.lower())
        if canon is None:
            invalid.append(t)
        elif canon not in seen:
            seen.add(canon)
            resolved.append(canon)
    return resolved, invalid


def render_config_toml(detected, priority, cities=None):
    """Render a full, commented config.toml from detected values. Pure.
    `priority` is an ordered list of country codes; `cities` optionally maps a
    country to an ordered city list (emits a [clash.cities] table)."""

    def toml_str(v):
        return json.dumps(v, ensure_ascii=False)

    cities = cities or {}
    cities_block = ""
    if cities:
        lines = "\n".join(f"{c} = {toml_str(list(v))}" for c, v in cities.items())
        cities_block = (
            "\n# Optional: city-level grouping + stickiness for specific countries.\n"
            f"[clash.cities]\n{lines}\n"
        )
    return _TEMPLATE.format(
        api=toml_str(detected.api),
        secret=toml_str(detected.secret),
        proxy_port=detected.proxy_port,
        profiles_yaml=toml_str(detected.profiles_yaml),
        priority=toml_str(list(priority)),
        cities_block=cities_block,
    )
