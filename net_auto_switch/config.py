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


@dataclass
class ClashPatterns:
    sg: str = r"(SG|Singapore|新加坡|🇸🇬)"
    jp: str = r"(JP|Japan|日本|🇯🇵)"
    tokyo: str = r"(Tokyo|东京)"
    trial: str = r"试用"


@dataclass
class ClashConfig:
    api: str = "http://127.0.0.1:9097"
    secret: str = ""
    proxy_port: int = 7890
    delay_limit: int = 300
    max_switch_per_min: int = 3
    max_profile_switch_per_30min: int = 1
    profiles_yaml: str = (
        "~/Library/Application Support/"
        "io.github.clash-verge-rev.clash-verge-rev/profiles.yaml"
    )
    group_priority: list = field(
        default_factory=lambda: ["SG", "Tokyo", "JP_Other"]
    )
    patterns: ClashPatterns = field(default_factory=ClashPatterns)


@dataclass
class Config:
    main_interval: int = 600
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
            "No config file found. Copy config.example.toml to config.toml "
            "and fill in your values."
        )
    with open(resolved, "rb") as f:
        data = tomllib.load(f)

    clash_data = dict(data.get("clash", {}))
    patterns_data = clash_data.pop("patterns", {})
    clash = _from_dict(ClashConfig, clash_data)
    clash.patterns = _from_dict(ClashPatterns, patterns_data)

    cfg = Config(
        main_interval=data.get("main_interval", Config.main_interval),
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
