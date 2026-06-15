import dataclasses
import os
import tomllib
from dataclasses import dataclass, field


class ConfigError(Exception):
    pass


@dataclass
class WifiConfig:
    enabled: bool = True
    check_interval: int = 3600
    switch_cooldown: int = 7200
    bad_latency_ms: float = 200
    bad_loss_pct: float = 5
    min_improvement_ms: float = 100
    interface: str = "en0"


# Region name -> regex matched (case-insensitive) against node names. Order
# matters: classification returns the first matching region, so list more
# specific regions before broader ones. Fully configurable — define any regions
# you like (US, HK, …); see docs/adr/0007.
DEFAULT_REGIONS = {
    "SG": r"(SG|Singapore|新加坡|🇸🇬)",
    "Tokyo": r"(Tokyo|东京)",
    "JP_Other": r"(JP|Japan|日本|🇯🇵)",
}
DEFAULT_TRIAL = r"试用"
# Optional: when the `target` region has no nodes by name, probe the `source`
# region's nodes and move those whose IP geolocates to `match` into `target`.
DEFAULT_IP_ENRICH = {"target": "Tokyo", "source": "JP_Other", "match": "tokyo"}


@dataclass
class ClashConfig:
    api: str = "http://127.0.0.1:9097"
    secret: str = ""
    proxy_port: int = 7890
    # Clash proxy group the daemon reads + switches. "auto" resolves it per cycle
    # from the live Clash mode (global -> GLOBAL, direct -> skip, rule -> the group
    # most connections route through). Set a literal group name to force one.
    managed_group: str = "auto"
    delay_limit: int = 300
    max_switch_per_min: int = 3
    max_profile_switch_per_30min: int = 1
    profiles_yaml: str = (
        "~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles.yaml"
    )
    group_priority: list = field(default_factory=lambda: ["SG", "Tokyo", "JP_Other"])
    regions: dict = field(default_factory=lambda: dict(DEFAULT_REGIONS))
    trial: str = DEFAULT_TRIAL
    ip_enrich: dict = field(default_factory=lambda: dict(DEFAULT_IP_ENRICH))


@dataclass
class Config:
    main_interval: int = 600
    # Pop up a macOS notification banner on every real switch (Clash node /
    # profile / WiFi). Never fires under --dry-run.
    notify: bool = True
    wifi: WifiConfig = field(default_factory=WifiConfig)
    clash: ClashConfig = field(default_factory=ClashConfig)


_SEARCH_PATHS = [
    "config.toml",
    os.path.expanduser("~/.config/net-auto-switch/config.toml"),
]


def _from_dict(cls, data):
    """Build a dataclass from a dict, ignoring unknown keys; absent keys use dataclass defaults."""
    fields = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in fields})


def _resolve_path(path):
    if path:
        return path if os.path.exists(path) else None
    for p in _SEARCH_PATHS:
        if os.path.exists(p):
            return p
    return None


def load_config(path=None):
    resolved = _resolve_path(path)
    if not resolved:
        raise ConfigError(
            "No config file found. Copy config.example.toml to config.toml and fill in your values."
        )
    with open(resolved, "rb") as f:
        data = tomllib.load(f)

    clash_data = dict(data.get("clash", {}))
    patterns_data = clash_data.pop("patterns", None)
    regions_data = clash_data.pop("regions", None)
    clash = _from_dict(ClashConfig, clash_data)
    if regions_data:
        clash.regions = dict(regions_data)
    elif patterns_data:
        # Backward compatibility: legacy [clash.patterns] (sg/jp/tokyo/trial).
        clash.regions = {
            "SG": patterns_data.get("sg", DEFAULT_REGIONS["SG"]),
            "Tokyo": patterns_data.get("tokyo", DEFAULT_REGIONS["Tokyo"]),
            "JP_Other": patterns_data.get("jp", DEFAULT_REGIONS["JP_Other"]),
        }
        clash.trial = patterns_data.get("trial", clash.trial)

    cfg = Config(
        main_interval=data.get("main_interval", Config.main_interval),
        notify=data.get("notify", Config.notify),
        wifi=_from_dict(WifiConfig, data.get("wifi", {})),
        clash=clash,
    )
    _validate(cfg)
    return cfg


def _validate(cfg):
    if cfg.main_interval <= 0:
        raise ConfigError("main_interval must be positive")
    if cfg.wifi.check_interval <= 0:
        raise ConfigError("wifi.check_interval must be positive")
    if cfg.wifi.switch_cooldown < 0:
        raise ConfigError("wifi.switch_cooldown must be >= 0")
    if not (0 < cfg.clash.proxy_port < 65536):
        raise ConfigError("clash.proxy_port out of range")
    if not cfg.clash.managed_group:
        raise ConfigError("clash.managed_group must be a non-empty group name")
    if not cfg.clash.regions:
        raise ConfigError("clash.regions must define at least one region")
    for g in cfg.clash.group_priority:
        if g not in cfg.clash.regions:
            raise ConfigError(
                f"group_priority references undefined region '{g}' "
                f"(defined: {list(cfg.clash.regions)})"
            )
