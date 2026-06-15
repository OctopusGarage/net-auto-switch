import argparse
import concurrent.futures
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .clash import ClashController
from .config import ClashConfig, ConfigError, load_config
from .orchestrator import Orchestrator
from .setup import (
    REGION_CATALOG,
    clash_verge_diagnosis,
    detect_clash_verge,
    detect_regions,
    health_check,
    probe_api,
    read_subscriptions,
    render_config_toml,
    resolve_priority,
)

log = logging.getLogger("net_auto_switch.cli")


def _default_log_path():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/net_auto_switch.log")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "net-auto-switch", "net_auto_switch.log")
    base = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
    return os.path.join(base, "net-auto-switch", "net_auto_switch.log")


LOG_PATH = _default_log_path()
LOG_BACKUP_DAYS = 14

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHD_LABEL = "com.octopusgarage.net-auto-switch"
LAUNCHD_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")
INSTALL_LAUNCHD = os.path.join(PROJECT_DIR, "scripts", "install-launchd.sh")
REPO = "OctopusGarage/net-auto-switch"


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


def _tag_from_release_url(url):
    """'.../releases/tag/v0.3.3' (optionally trailing /) -> 'v0.3.3'."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def _version_tuple(v):
    """'v0.3.10' -> (0, 3, 10); ignores any non-numeric suffix."""
    return tuple(int(n) for n in re.findall(r"\d+", v))


def _is_newer(candidate, current):
    return _version_tuple(candidate) > _version_tuple(current)


def _installed_version():
    try:
        import tomllib

        with open(os.path.join(PROJECT_DIR, "pyproject.toml"), "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return None


def _resolve_latest_tag():
    """Resolve the latest release tag by following the /releases/latest redirect."""
    try:
        r = subprocess.run(
            [
                "curl",
                "-fsSLI",
                "-o",
                "/dev/null",
                "-w",
                "%{url_effective}",
                f"https://github.com/{REPO}/releases/latest",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode != 0:
            return None
        tag = _tag_from_release_url(r.stdout.strip())
        return tag if tag.startswith("v") else None
    except Exception:
        return None


# Runtime state preserved across an update; everything else is replaced by the
# extracted release, so files dropped between versions don't linger.
_PRESERVE_ON_UPDATE = {"config.toml", "config.toml.bak", ".venv", "logs", ".net-auto-switch.pid"}


def _prune_for_clean_extract(dest):
    """Remove stale files from `dest` before extracting a new release.

    Preserves runtime state (config, venv, logs). No-op on a dev checkout (has
    `.git`) or anything that doesn't already look like an install, so it can't
    nuke a source tree or an unrelated directory."""
    if not os.path.isdir(dest) or os.path.exists(os.path.join(dest, ".git")):
        return
    looks_like_install = os.path.isdir(os.path.join(dest, "net_auto_switch")) or os.path.exists(
        os.path.join(dest, "pyproject.toml")
    )
    if not looks_like_install:
        return
    for name in os.listdir(dest):
        if name in _PRESERVE_ON_UPDATE:
            continue
        path = os.path.join(dest, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)


def _download_release(tag, dest):
    """Download the release tarball for `tag` and extract it over `dest`.

    Prefers the curated lean asset (`net-auto-switch-<tag>.tar.gz`) and falls back
    to the full source archive for older releases that predate it. Stale files are
    pruned first (preserving config + venv + logs) so nothing dropped between
    versions lingers; config.toml is preserved and not in either archive."""
    asset = f"https://github.com/{REPO}/releases/download/{tag}/net-auto-switch-{tag}.tar.gz"
    source = f"https://github.com/{REPO}/archive/refs/tags/{tag}.tar.gz"
    tmp = tempfile.mkdtemp()
    try:
        tarball = os.path.join(tmp, "release.tar.gz")
        ok = subprocess.run(["curl", "-fsSL", asset, "-o", tarball]).returncode == 0 or (
            subprocess.run(["curl", "-fsSL", source, "-o", tarball]).returncode == 0
        )
        if not ok:
            return False
        os.makedirs(dest, exist_ok=True)
        _prune_for_clean_extract(dest)
        extract = ["tar", "-xzf", tarball, "--strip-components=1", "-C", dest]
        return subprocess.run(extract).returncode == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    # Rotate the log at midnight and keep LOG_BACKUP_DAYS days, so it never grows
    # unbounded for a long-running daemon. Routine logs go to stdout (captured as
    # launchd.out.log); only real errors / pre-logging crashes hit stderr.
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_PATH, when="midnight", backupCount=LOG_BACKUP_DAYS, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=[file_handler, logging.StreamHandler(sys.stdout)],
        force=True,
    )


def _confirm(prompt, default=True):
    suffix = "[Y/n]" if default else "[y/N]"
    ans = input(f"{prompt} {suffix} ").strip().lower()
    if not ans:
        return default
    return ans in ("y", "yes")


def cmd_init(argv):
    """Guided setup: auto-detect Clash Verge, write config.toml, optionally
    install the launchd service and start it."""
    p = argparse.ArgumentParser(prog="net-auto-switch init", description="Guided setup wizard")
    p.add_argument("-y", "--yes", action="store_true", help="Accept defaults, no prompts")
    p.add_argument("--config", default="config.toml", help="Output config path")
    p.add_argument("--no-service", action="store_true", help="Skip the launchd service step")
    args = p.parse_args(argv)

    if sys.platform != "darwin":
        print("✗ The guided `init` wizard is macOS-only (Clash Verge auto-detection + launchd).")
        print("  The Clash node auto-switch core works cross-platform, though — on Linux/Windows:")
        print("    1. cp config.example.toml config.toml")
        print("    2. fill in your Clash API url / secret / proxy_port")
        print("    3. run:  uv run net-auto-switch --once --dry-run   (then without --dry-run)")
        print("    4. install the background service (systemd / Task Scheduler):")
        print("         uv run net-auto-switch service install")
        print("  Note: WiFi switching, desktop notifications, and profile fallback are macOS-only.")
        return 1

    print("🔍 Detecting Clash Verge…")
    detected = detect_clash_verge()
    if detected is None:
        print(f"✗ {clash_verge_diagnosis()}")
        return 1
    secret_state = "(set)" if detected.secret else "(empty)"
    print(f"✓ api={detected.api}  proxy_port={detected.proxy_port}  secret={secret_state}")
    print(f"✓ profiles.yaml: {detected.profiles_yaml}")

    try:
        version = probe_api(detected.api, detected.secret)
        print(f"✓ Connected to Clash API (version {version})")
    except Exception as e:
        import requests

        status = getattr(getattr(e, "response", None), "status_code", None)
        if isinstance(e, requests.exceptions.HTTPError) and status in (401, 403):
            print("⚠ Clash API reachable but the secret was rejected (it may have changed).")
            print("  Check Clash Verge → Settings → External Controller secret; then re-run.")
        elif isinstance(e, requests.exceptions.ConnectionError):
            print("⚠ Can't reach the Clash API — Clash Verge isn't running, or its external")
            print("  controller is off. Open Clash Verge → Settings → enable the external")
            print("  controller (Clash API), confirm it's running, then re-run.")
        else:
            print(f"⚠ Could not reach Clash API: {e}")
        if not args.yes and not _confirm("Continue anyway?", default=False):
            return 1

    # Health gate: make sure the subscription actually has working nodes before
    # we finish setup. We can't reliably trigger a Clash Verge subscription update
    # from here (see ADR-0009), so on failure we point the user at the fix.
    try:
        reachable, total = health_check(detected.api, detected.secret)
        print(f"✓ Health check: {reachable}/{total} nodes reachable")
        if reachable == 0:
            print(
                "⚠ No reachable nodes. In Clash Verge, update your subscription "
                "(right-click the profile → Update) or check that it hasn't expired, "
                "then re-run this."
            )
            if not args.yes and not _confirm("Continue setup anyway?", default=False):
                return 1
    except Exception as e:
        print(f"⚠ Health check skipped ({e})")

    # Subscription preflight (read-only): surface auto-update / expiry / traffic so
    # the user can fix a stale subscription in Clash Verge before relying on it.
    subs = read_subscriptions(detected.profiles_yaml)
    if subs:
        now = time.time()
        print("✓ Subscriptions:")
        needs_autoupdate = False
        for s in subs:
            auto = s["update_interval"] > 0 and s["allow_auto_update"]
            au = f"auto-update every {s['update_interval']}m" if auto else "auto-update OFF"
            print(f"    {s['name']}: {au}")
            needs_autoupdate = needs_autoupdate or not auto
            if s["expire"]:
                days = (s["expire"] - now) / 86400
                if days < 0:
                    print("      ⚠ EXPIRED — renew the subscription")
                elif days < 7:
                    print(f"      ⚠ expires in ~{int(days)} day(s)")
            if s["total"]:
                pct = s["used"] / s["total"] * 100
                if pct >= 90:
                    print(f"      ⚠ traffic ~{pct:.0f}% used")
        if needs_autoupdate:
            print(
                "  → Enable auto-update in Clash Verge: Profiles → right-click the "
                "subscription → Edit → set 'Update Interval' (minutes)."
            )

    group_priority = list(ClashConfig.__dataclass_fields__["group_priority"].default_factory())
    regions = None
    try:
        ctrl = ClashController(
            ClashConfig(api=detected.api, secret=detected.secret, proxy_port=detected.proxy_port)
        )
        names = [
            n
            for n, d in ctrl.get_proxies().items()
            if d.get("type") not in ("Selector", "URLTest", "Fallback")
        ]
        counts = detect_regions(names)
        if counts:
            print("  Regions found in your subscription:")
            for name, c in counts.items():
                print(f"    {name:8} x{c}")
            valid = list(counts)  # detected region names, most-common first
            chosen = valid
            if not args.yes:
                print(f"  Choose priority order from: {', '.join(valid)}")
                while True:
                    ans = input(
                        "  Enter names comma-separated (e.g. JP,SG), or just Enter for all: "
                    ).strip()
                    if not ans:
                        chosen = valid
                        break
                    resolved, invalid = resolve_priority(ans, valid)
                    if invalid:
                        print(f"  ✗ not in the list: {', '.join(invalid)} — pick from {valid}")
                        continue
                    if not resolved:
                        print("  ✗ nothing recognized — try again, or press Enter for all")
                        continue
                    chosen = resolved
                    break
            # Build regions in catalog order (specific-first) for correct matching;
            # group_priority keeps the user's chosen order for fallback.
            regions = {n: REGION_CATALOG[n] for n in REGION_CATALOG if n in chosen}
            group_priority = chosen
    except Exception:
        pass  # detection is best-effort; falls back to the default regions

    out = args.config
    if os.path.exists(out):
        backup = out + ".bak"
        shutil.copy2(out, backup)
        os.chmod(backup, 0o600)  # the config carries the Clash secret — owner-only
        print(f"• Backed up existing {out} -> {backup}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_config_toml(detected, group_priority, regions))
    os.chmod(out, 0o600)  # the config carries the Clash secret — owner-only
    print(f"✓ Wrote {out}")

    try:
        load_config(out)
        print("✓ Config valid")
    except ConfigError as e:
        print(f"✗ Config invalid: {e}")
        return 1

    if not args.no_service and (args.yes or _confirm("Install launchd service and start now?")):
        subprocess.run(["bash", INSTALL_LAUNCHD], check=False)

    print("\nOne-time checklist (in Clash Verge / macOS):")
    print("  • Launch Clash Verge at login so its API + subscription auto-update stay available")
    print("  • Profile fallback needs Accessibility: System Settings → Privacy & Security")
    print("    → Accessibility (allow your terminal / the launchd agent)")
    print("  • WiFi auto-switch / SSID reads may need Location Services on recent macOS:")
    print("    System Settings → Privacy & Security → Location Services")
    print("🎉 Done. Try a dry run: uv run net-auto-switch --once --dry-run")
    return 0


def cmd_update(argv):
    """Update an existing install: download the latest release, re-sync, reload."""
    p = argparse.ArgumentParser(prog="net-auto-switch update", description="Update to latest")
    p.add_argument("--no-restart", action="store_true", help="Don't reload the launchd service")
    p.add_argument("--force", action="store_true", help="Reinstall even if already current")
    p.add_argument("--version", default=None, help="Install a specific tag (default: latest)")
    args = p.parse_args(argv)

    target = args.version or _resolve_latest_tag()
    if not target:
        print("✗ Couldn't determine the latest release (network issue?).")
        return 1

    installed = _installed_version()
    if not args.force and not args.version and installed and not _is_newer(target, installed):
        print(f"✓ Already up to date (v{installed}).")
        return 0

    print(f"⬇️  Downloading {target}…")
    if not _download_release(target, PROJECT_DIR):
        print(f"✗ Couldn't download/extract {target}. Your install is unchanged.")
        return 1

    if not args.no_restart and os.path.exists(LAUNCHD_PLIST):
        # install-launchd.sh re-syncs deps, regenerates the plist, and reloads it.
        print("🔄 Re-syncing and reloading service…")
        subprocess.run(["bash", INSTALL_LAUNCHD], check=False)
    else:
        print("📦 Syncing dependencies…")
        subprocess.run(["uv", "sync"], cwd=PROJECT_DIR, check=False)
        if not os.path.exists(LAUNCHD_PLIST):
            print("ℹ Service not installed; restart manually if running.")

    print("🎉 Up to date.")
    return 0


def _read_yaml_mapping(path):
    import yaml

    with open(os.path.expanduser(path), encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _profile_file_candidates(profiles_yaml, profile):
    base = os.path.dirname(os.path.expanduser(profiles_yaml))
    names = []
    for key in ("file", "path", "name"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    uid = profile.get("uid")
    if isinstance(uid, str) and uid.strip():
        names.append(f"{uid.strip()}.yaml")

    candidates = []
    seen = set()
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


def _load_current_profile_nodes(profiles_yaml):
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

    profile_data = {}
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


def _is_clash_proxy_node(data):
    proxy_type = str(data.get("type") or "")
    return bool(proxy_type) and proxy_type not in _CLASH_NON_NODE_TYPES and "all" not in data


def _load_clash_api_nodes(clash_cfg):
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


def _load_clash_api_profile(clash_cfg):
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


def _unique_servers(nodes):
    servers = []
    seen = set()
    for node in nodes:
        server = node["server"]
        if server in seen:
            continue
        seen.add(server)
        servers.append(server)
    return servers


def _print_clash_profile_whois(profile, lookup_by_server):
    from . import whois

    nodes = profile["nodes"]
    name_width = max([len(n["name"]) for n in nodes] + [4])
    server_width = max([len(n["server"]) for n in nodes] + [6])
    ips = [result.ip for results in lookup_by_server.values() for result in results]
    ip_width = max([len(ip) for ip in ips] + [2, 15])

    print(f"=== [{profile['name']}] uid={profile['uid']}  节点数: {len(nodes)} <- current ===")
    for node in nodes:
        results = lookup_by_server.get(node["server"]) or []
        if not results:
            print(
                f"{node['name']:<{name_width}}  "
                f"{node['server']:<{server_width}}  "
                f"{'解析失败':<{ip_width}}  解析失败"
            )
            continue
        for index, result in enumerate(results):
            node_name = node["name"] if index == 0 else ""
            server = node["server"] if index == 0 else ""
            operator = whois.format_operator(result.operator, result.country)
            print(
                f"{node_name:<{name_width}}  "
                f"{server:<{server_width}}  "
                f"{result.ip:<{ip_width}}  "
                f"{operator}"
            )


def _cmd_whois_current_clash_profile(args, use_doh):
    from . import whois

    try:
        clash_cfg = _resolve_whois_clash_config(args.config)
        profile = _load_clash_api_profile(clash_cfg)
    except (ConfigError, WhoisProfileError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    servers = _unique_servers(profile["nodes"])
    total = len(servers)
    print(f"待解析 server 数 (去重后): {total}\n")

    # Each lookup is network-bound (DoH + whois with retries) and slow; run them
    # concurrently and report per-server progress to stderr so the table on stdout
    # stays pipe-clean. Output ordering is unaffected — the table re-keys by server.
    lookup_by_server = {}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, total or 1)) as executor:
        future_to_server = {
            executor.submit(whois.lookup, server, args.server, args.authoritative, use_doh): server
            for server in servers
        }
        for future in concurrent.futures.as_completed(future_to_server):
            server = future_to_server[future]
            try:
                lookup_by_server[server] = future.result()
            except Exception as e:  # noqa: BLE001 - a single bad server shouldn't abort the scan
                lookup_by_server[server] = []
                print(f"  ⚠ {server} 查询出错: {e}", file=sys.stderr)
            done += 1
            print(f"[{done}/{total}] {server}", file=sys.stderr)

    _print_clash_profile_whois(profile, lookup_by_server)
    return 0


def _resolve_whois_clash_config(config_path):
    try:
        return load_config(config_path).clash
    except ConfigError:
        if config_path:
            raise
        detected = detect_clash_verge()
        if detected:
            return ClashConfig(
                api=detected.api,
                secret=detected.secret,
                proxy_port=detected.proxy_port,
                profiles_yaml=detected.profiles_yaml,
            )
        raise


def cmd_whois(argv):
    """Resolve a domain / IP to its operator or cloud provider."""
    from . import whois

    p = argparse.ArgumentParser(
        prog="net-auto-switch whois",
        description="解析域名/IP 对应的运营商",
    )
    p.add_argument("-s", "--server", default="1.1.1.1", help="指定 DNS 服务器 (默认 1.1.1.1)")
    p.add_argument(
        "-a",
        "--authoritative",
        action="store_true",
        help="查询域名的权威 NS, 再向该 NS 直接发起 A 查询 (隐含 --no-doh)",
    )
    p.add_argument(
        "--no-doh",
        dest="doh",
        action="store_false",
        default=True,
        help="改用系统 DNS 解析 (默认走 Cloudflare DoH 绕开 TUN 模式劫持)",
    )
    p.add_argument(
        "--config",
        default=None,
        help="Path to config.toml (仅在不传 target、扫描 Clash 节点时使用)",
    )
    p.add_argument(
        "targets",
        nargs="*",
        help="域名或 IP；不传则查询当前 Clash profile 的节点 server",
    )
    args = p.parse_args(argv)

    # DoH is HTTPS-based; -a relies on plaintext DNS to a specific NS, so the two
    # are mutually exclusive. Asking for -a implicitly turns DoH off.
    use_doh = args.doh and not args.authoritative
    if not args.targets:
        return _cmd_whois_current_clash_profile(args, use_doh)
    for target in args.targets:
        whois.analyze(target.strip(), args.server, args.authoritative, use_doh)
    return 0


def cmd_service(argv):
    """Install/uninstall/check the background service using the platform-native
    mechanism (launchd on macOS, systemd --user on Linux, Task Scheduler on Windows)."""
    from . import service

    p = argparse.ArgumentParser(
        prog="net-auto-switch service",
        description="Manage the background service (launchd / systemd / Task Scheduler)",
    )
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.add_argument("--config", default=None, help="Path to config.toml (for install)")
    args = p.parse_args(argv)

    config_path = os.path.abspath(args.config or os.path.join(PROJECT_DIR, "config.toml"))

    if args.action == "uninstall":
        return 0 if service.uninstall() else 1
    if args.action == "status":
        return 0 if service.status() else 1

    # install
    if not os.path.exists(config_path):
        print(f"✗ No config at {config_path}. Copy config.example.toml and fill it in first.")
        return 1
    # Windows runs `--once` on a timer; derive the interval from main_interval.
    interval_minutes = 10
    try:
        interval_minutes = max(1, load_config(config_path).main_interval // 60)
    except ConfigError:
        pass
    print("📦 Syncing dependencies (uv sync)…")
    subprocess.run(["uv", "sync"], cwd=PROJECT_DIR, check=False)
    ok = service.install(PROJECT_DIR, config_path, interval_minutes)
    print("✓ Service installed." if ok else "✗ Service install failed (see output above).")
    return 0 if ok else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "init":
        sys.exit(cmd_init(argv[1:]))
    if argv and argv[0] == "update":
        sys.exit(cmd_update(argv[1:]))
    if argv and argv[0] == "whois":
        sys.exit(cmd_whois(argv[1:]))
    if argv and argv[0] == "service":
        sys.exit(cmd_service(argv[1:]))

    parser = argparse.ArgumentParser(description="net-auto-switch")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without switching")
    parser.add_argument("--config", default=None, help="Path to config.toml")
    args = parser.parse_args(argv)

    _setup_logging()
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        log.error(f"Config error: {e}")
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    mode = "single cycle" if args.once else "continuous"
    log.info(
        f"Starting net-auto-switch (mode={mode}, dry_run={args.dry_run}, "
        f"config={args.config or 'auto'}, wifi_enabled={cfg.wifi.enabled})"
    )
    orch = Orchestrator(cfg, dry_run=args.dry_run)
    if args.once:
        orch.run_once()
    else:
        orch.run_forever()


if __name__ == "__main__":
    main()
