"""Auto-detect Clash Verge settings and render a ready-to-use config.toml.

The pure functions here (parse / render) are unit-tested; the thin I/O wrappers
(detect / probe) just read files and hit the local API.
"""

import json
import os
from dataclasses import dataclass

import yaml

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

# Region name -> regex, matched in order (first match wins). Define any regions
# you like — e.g. a US-first setup: group_priority = ["US", "JP"] with US/JP here.
[clash.regions]
SG = "(SG|Singapore|新加坡|🇸🇬)"
Tokyo = "(Tokyo|东京)"
JP_Other = "(JP|Japan|日本|🇯🇵)"

# Optional: when Tokyo has no nodes by name, probe JP_Other nodes and move those
# whose IP geolocates to Tokyo into it. Remove this table to disable.
[clash.ip_enrich]
target = "Tokyo"
source = "JP_Other"
match = "tokyo"
"""


def render_config_toml(detected, group_priority):
    """Render a full, commented config.toml from detected values. Pure.

    json.dumps yields valid TOML basic strings / arrays, so it safely quotes
    secrets and paths that contain spaces or special characters.
    """
    return _TEMPLATE.format(
        api=json.dumps(detected.api),
        secret=json.dumps(detected.secret),
        proxy_port=detected.proxy_port,
        profiles_yaml=json.dumps(detected.profiles_yaml),
        group_priority=json.dumps(group_priority),
    )
