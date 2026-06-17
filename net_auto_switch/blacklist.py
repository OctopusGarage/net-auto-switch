"""Pure blacklist matchers + a small persisted 'learned bad exit' store.

The learned store is {node name: epoch-seconds when it was last seen bad};
entries older than relearn_days are treated as expired (the node gets a fresh
chance, since a node's exit can change)."""

import json
import os


def operator_blacklisted(operator, patterns):
    low = (operator or "").lower()
    return any(p.lower() in low for p in patterns if p)


def country_blacklisted(country, countries):
    if not country:
        return False
    up = country.upper()
    return any(up == c.upper() for c in countries)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_learned(path, relearn_days, now):
    horizon = relearn_days * 86400
    return {name for name, ts in _read(path).items() if now - ts < horizon}


def record_learned(path, name, now, relearn_days=7):
    horizon = relearn_days * 86400
    data = {k: v for k, v in _read(path).items() if now - v < horizon}
    data[name] = now
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
