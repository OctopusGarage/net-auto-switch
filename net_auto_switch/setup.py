"""Auto-detect Clash Verge settings and render a ready-to-use config.toml.

The pure functions here (parse / render) are unit-tested; the thin I/O wrappers
(detect / probe) just read files and hit the local API.
"""

import json
import os
import re
from dataclasses import dataclass

import yaml

from .config import DEFAULT_REGIONS

# Clash Verge keeps its merged runtime config and profiles here on macOS.
CLASH_VERGE_DIR = os.path.expanduser(
    "~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev"
)
RUNTIME_CONFIG = "clash-verge.yaml"
PROFILES_YAML = "profiles.yaml"


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
group_priority = {group_priority}

# Region name -> regex, matched in order (first match wins).
[clash.regions]
{regions_block}
{ip_enrich_block}"""


# Common regions, specific-first (Tokyo before JP), for detecting what's actually
# in a subscription. The `init` wizard counts node-name matches against these and
# lets you pick which to prioritize.
REGION_CATALOG = {
    "Tokyo": r"(Tokyo|东京)",
    "JP": r"(JP|Japan|日本|🇯🇵)",
    "SG": r"(SG|Singapore|新加坡|🇸🇬)",
    "HK": r"(HK|Hong ?Kong|香港|🇭🇰)",
    "TW": r"(TW|Taiwan|台湾|台灣|🇹🇼)",
    "US": r"(US|United States|美国|美國|洛杉矶|圣何塞|🇺🇸)",
    "KR": r"(KR|Korea|韩国|首尔|🇰🇷)",
    "UK": r"(UK|United Kingdom|英国|🇬🇧)",
    "DE": r"(DE|Germany|德国|🇩🇪)",
}


def detect_regions(node_names, catalog=None):
    """Count how many node names match each catalog region. Returns a dict of
    {region: count} for regions with ≥1 match, sorted by count (desc). Pure."""
    catalog = catalog or REGION_CATALOG
    counts = {}
    for name, rx in catalog.items():
        cre = re.compile(rx, re.IGNORECASE)
        c = sum(1 for n in node_names if cre.search(n))
        if c:
            counts[name] = c
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def render_config_toml(detected, group_priority, regions=None):
    """Render a full, commented config.toml from detected values. Pure.

    `regions` is an ordered name->regex map; defaults to SG/Tokyo/JP_Other. The
    Tokyo IP-enrich table is emitted only for that default JP layout. json.dumps
    yields valid TOML strings/arrays, safely quoting special characters.
    """
    # ensure_ascii=False keeps emoji / CJK literal — TOML allows them, but TOML
    # basic strings reject the surrogate-pair \u escapes json.dumps emits by default.
    def toml_str(v):
        return json.dumps(v, ensure_ascii=False)

    regions = regions or dict(DEFAULT_REGIONS)
    regions_block = "\n".join(f"{n} = {toml_str(rx)}" for n, rx in regions.items())
    ip_enrich_block = ""
    if "Tokyo" in regions and "JP_Other" in regions:
        ip_enrich_block = (
            "\n# When Tokyo has no nodes by name, probe JP_Other nodes and move those\n"
            "# whose IP geolocates to Tokyo into it. Remove this table to disable.\n"
            '[clash.ip_enrich]\ntarget = "Tokyo"\nsource = "JP_Other"\nmatch = "tokyo"\n'
        )
    return _TEMPLATE.format(
        api=toml_str(detected.api),
        secret=toml_str(detected.secret),
        proxy_port=detected.proxy_port,
        profiles_yaml=toml_str(detected.profiles_yaml),
        group_priority=toml_str(group_priority),
        regions_block=regions_block,
        ip_enrich_block=ip_enrich_block,
    )
