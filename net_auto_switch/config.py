import dataclasses
import os
import sys
import tomllib
from dataclasses import dataclass, field

from .geo import catalog as geo_catalog

# Built-in fallback country priority when the user / wizard sets none.
DEFAULT_PRIORITY = ["SG", "HK", "JP", "TW", "KR", "US", "GB", "DE"]

# Legacy [clash] group_priority used region NAMES (incl. city-level Tokyo/JP_Other);
# translate them to country codes when mapping an old config to the new `priority`.
_LEGACY_REGION_TO_COUNTRY = {"Tokyo": "JP", "JP_Other": "JP"}


class ConfigError(Exception):
    pass


def _default_profiles_yaml():
    """Clash Verge Rev's profiles.yaml, per-platform. Only read for the (macOS-only)
    profile fallback; non-macOS defaults are best-effort."""
    name = "io.github.clash-verge-rev.clash-verge-rev"
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, name, "profiles.yaml")


@dataclass
class WifiConfig:
    enabled: bool = True
    check_interval: int = 3600
    switch_cooldown: int = 7200
    bad_latency_ms: float = 200
    bad_loss_pct: float = 5
    min_improvement_ms: float = 100
    interface: str = "en0"


DEFAULT_TRIAL = r"试用"


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
    profiles_yaml: str = field(default_factory=_default_profiles_yaml)
    trial: str = DEFAULT_TRIAL
    priority: list = field(default_factory=lambda: list(DEFAULT_PRIORITY))
    cities: dict = field(default_factory=dict)
    region_overrides: dict = field(default_factory=dict)
    blacklist: dict = field(default_factory=dict)
    state_dir: str = ""


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
    if not regions_data and patterns_data:
        # Backward compatibility: legacy [clash.patterns] (sg/jp/tokyo/trial).
        overrides: dict[str, str] = {}
        if "sg" in patterns_data:
            overrides["SG"] = patterns_data["sg"]
        if "tokyo" in patterns_data:
            overrides["Tokyo"] = patterns_data["tokyo"]
        if "jp" in patterns_data:
            overrides["JP_Other"] = patterns_data["jp"]
        if overrides:
            clash.region_overrides = overrides
        clash.trial = patterns_data.get("trial", clash.trial)

    raw_clash = data.get("clash", {})
    if "cities" in raw_clash:
        clash.cities = {k: list(v) for k, v in raw_clash["cities"].items()}
    if regions_data:
        clash.region_overrides = dict(regions_data)
    if "priority" in raw_clash:
        clash.priority = list(raw_clash["priority"])
    elif "group_priority" in raw_clash:
        seen: set[str] = set()
        priority: list[str] = []
        for entry in raw_clash["group_priority"]:
            code = (
                entry
                if entry in geo_catalog.COUNTRY_TOKENS
                else _LEGACY_REGION_TO_COUNTRY.get(entry)
            )
            if code and code not in seen:
                seen.add(code)
                priority.append(code)
        if priority:
            clash.priority = priority

    if "blacklist" in raw_clash:
        clash.blacklist = dict(raw_clash["blacklist"])
    clash.state_dir = os.path.dirname(os.path.abspath(resolved))

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
    if not cfg.clash.priority:
        raise ConfigError("clash.priority must list at least one country")
    known = set(geo_catalog.COUNTRY_TOKENS) | set(cfg.clash.region_overrides)
    for code in cfg.clash.priority:
        if code not in known:
            raise ConfigError(
                f"clash.priority references unknown country '{code}' (known: {sorted(known)})"
            )
    for country in cfg.clash.cities:
        if country not in cfg.clash.priority:
            raise ConfigError(f"clash.cities country '{country}' is not in clash.priority")
