"""Shared reader for Clash proxy nodes and their server addresses.

Extracted from cli.py so the daemon can reuse the loader functions
without depending on the CLI layer.

NOTE: ClashController is imported at module level here so tests can monkeypatch
`nodes_src.ClashController`. When Task 7 adds a clash→nodes_src import, this
will need to become a lazy (inside-function) import to break the cycle.
"""

from __future__ import annotations

import os

import yaml

from .clash import ClashController
from .config import ClashConfig


class WhoisProfileError(Exception):
    pass


_CLASH_GROUP_TYPES = {"Selector", "URLTest", "Fallback", "LoadBalance", "Relay"}
_CLASH_NON_NODE_TYPES = _CLASH_GROUP_TYPES | {
    "Compatible",
    "Direct",
    "Pass",
    "Reject",
    "RejectDrop",
}


def _read_yaml_mapping(path: str) -> dict:
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _profile_file_candidates(profiles_yaml: str, profile: dict) -> list[str]:
    base = os.path.dirname(os.path.expanduser(profiles_yaml))
    names: list[str] = []
    for key in ("file", "path", "name"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    uid = profile.get("uid")
    if isinstance(uid, str) and uid.strip():
        names.append(f"{uid.strip()}.yaml")

    candidates: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not name.endswith((".yaml", ".yml")):
            continue
        paths = (
            [name]
            if os.path.isabs(name)
            else [os.path.join(base, name), os.path.join(base, "profiles", name)]
        )
        for path in paths:
            expanded = os.path.expanduser(path)
            if expanded not in seen:
                seen.add(expanded)
                candidates.append(expanded)
    return candidates


def _load_current_profile_nodes(profiles_yaml: str) -> dict:
    profiles_path = os.path.expanduser(profiles_yaml)
    try:
        data = _read_yaml_mapping(profiles_path)
    except Exception as e:
        raise WhoisProfileError(f"Failed to read profiles.yaml: {e}") from e

    current_uid = data.get("current")
    items = data.get("items") or []
    if not isinstance(items, list):
        raise WhoisProfileError("profiles.yaml has no valid items list")
    profile = next((p for p in items if isinstance(p, dict) and p.get("uid") == current_uid), None)
    if profile is None:
        raise WhoisProfileError(f"Current profile not found in profiles.yaml: {current_uid}")

    profile_data: dict = {}
    if isinstance(profile.get("proxies"), list):
        profile_data = profile
    else:
        for candidate in _profile_file_candidates(profiles_path, profile):
            if not os.path.exists(candidate):
                continue
            try:
                profile_data = _read_yaml_mapping(candidate)
            except Exception:
                continue
            if isinstance(profile_data.get("proxies"), list):
                break

    proxies = profile_data.get("proxies") or []
    if not isinstance(proxies, list):
        proxies = []

    nodes = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        server = str(proxy.get("server") or "").strip()
        if not server:
            continue
        name = str(proxy.get("name") or server).strip()
        nodes.append({"name": name, "server": server})

    if not nodes:
        raise WhoisProfileError(f"No proxy server entries found for current profile: {current_uid}")

    profile_name = profile.get("name") or current_uid or profile.get("file") or "?"
    return {"uid": current_uid or "?", "name": profile_name, "nodes": nodes}


def _is_clash_proxy_node(data: dict) -> bool:
    proxy_type = str(data.get("type") or "")
    return bool(proxy_type) and proxy_type not in _CLASH_NON_NODE_TYPES and "all" not in data


def _load_clash_api_nodes(clash_cfg: ClashConfig) -> list[dict]:
    try:
        proxies = ClashController(clash_cfg).get_proxies()
    except Exception as e:
        raise WhoisProfileError(f"Failed to read Clash API proxies: {e}") from e

    nodes = []
    for name, data in proxies.items():
        if not isinstance(data, dict) or not _is_clash_proxy_node(data):
            continue
        node_name = str(data.get("name") or name).strip()
        server = str(data.get("server") or "").strip()
        if node_name:
            nodes.append({"name": node_name, "server": server})

    if not nodes:
        raise WhoisProfileError("No proxy nodes found from Clash API")
    return nodes


def _load_clash_api_profile(clash_cfg: ClashConfig) -> dict:
    api_nodes = _load_clash_api_nodes(clash_cfg)
    try:
        profile = _load_current_profile_nodes(clash_cfg.profiles_yaml)
    except WhoisProfileError:
        profile = {"uid": "Clash API", "name": "Clash API", "nodes": []}

    server_by_name = {node["name"]: node["server"] for node in profile["nodes"]}
    nodes = []
    for node in api_nodes:
        server = node["server"] or server_by_name.get(node["name"], "")
        if server:
            nodes.append({"name": node["name"], "server": server})

    if not nodes:
        raise WhoisProfileError(
            "Clash API returned proxy nodes but did not expose their server endpoints"
        )
    return {"uid": profile["uid"], "name": profile["name"], "nodes": nodes}


def _unique_servers(nodes: list[dict]) -> list[str]:
    servers: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        server = node["server"]
        if server in seen:
            continue
        seen.add(server)
        servers.append(server)
    return servers


def node_servers(clash_cfg: ClashConfig) -> dict[str, str]:
    """Return a mapping of node name -> server address for all Clash API nodes.

    Returns an empty dict if the profile cannot be loaded (e.g., Clash is not running).
    """
    try:
        profile = _load_clash_api_profile(clash_cfg)
    except WhoisProfileError:
        return {}
    return {n["name"]: n["server"] for n in profile["nodes"]}
