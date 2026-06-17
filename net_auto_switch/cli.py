import argparse
import concurrent.futures
import logging
import logging.handlers
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .clash import ClashController, aggregate_connections, summarize_connections
from .config import ClashConfig, ConfigError, load_config
from .orchestrator import Orchestrator
from .setup import (
    clash_verge_diagnosis,
    detect_cities,
    detect_clash_verge,
    detect_regions,
    health_check,
    parse_index_order,
    probe_api,
    read_subscriptions,
    render_config_toml,
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


def _print_numbered(labels):
    for i, label in enumerate(labels, 1):
        print(f"    {i}) {label}")


def _prompt_priority(counts):
    """Ask the user to order detected countries by typing indices. Returns the
    ordered country codes; Enter (or only-invalid input) → all, count-sorted."""
    items = list(counts)  # country codes, most-common first
    print("  检测到订阅里的国家 (按节点数):")
    _print_numbered([f"{cc} ({counts[cc]})" for cc in items])
    prompt = "  优先顺序编号 (空格分隔, 例 1 3 4), 回车=按节点数: "
    while True:
        ans = input(prompt).strip()
        if not ans:
            return items
        ordered, invalid = parse_index_order(ans, items)
        if invalid:
            print(f"  ✗ 无效编号: {', '.join(invalid)} (有效 1-{len(items)})")
            continue
        return ordered


def _prompt_cities(country, city_counts):
    """Ask whether to split `country` by its detected cities. Returns the ordered
    city list (empty → no city grouping). Invalid indices are ignored."""
    cities = list(city_counts)
    print(f"  {country} 检测到城市:")
    _print_numbered([f"{c} ({city_counts[c]})" for c in cities])
    ans = input("  按优先输入编号 (回车=不按城市细分): ").strip()
    if not ans:
        return []
    ordered, invalid = parse_index_order(ans, cities)
    if invalid:
        print(f"  ⚠ 忽略无效编号: {', '.join(invalid)}")
    return ordered


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

    priority = list(ClashConfig.__dataclass_fields__["priority"].default_factory())
    cities = {}
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
        ccounts = detect_cities(names)
        if counts:
            if args.yes or not sys.stdin.isatty():
                priority = list(counts)  # non-interactive: all, count-sorted
            else:
                priority = _prompt_priority(counts)
                for cc in priority:
                    if cc in ccounts:
                        picked = _prompt_cities(cc, ccounts[cc])
                        if picked:
                            cities[cc] = picked
                summary = " > ".join(
                    f"{cc}[{'/'.join(cities[cc])}]" if cc in cities else cc for cc in priority
                )
                print(f"  ✓ 优先级: {summary}")
    except Exception:
        cities = {}  # detection is best-effort; falls back to the default priority

    out = args.config
    if os.path.exists(out):
        backup = out + ".bak"
        shutil.copy2(out, backup)
        os.chmod(backup, 0o600)  # the config carries the Clash secret — owner-only
        print(f"• Backed up existing {out} -> {backup}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_config_toml(detected, priority, cities=cities))
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


def _whois_concurrent(items, server, authoritative, use_doh):
    """Run whois.lookup over `items` concurrently, yielding (item, future) as each
    completes. Capped at 8 workers — whois servers are rate-limit sensitive — and
    centralised here so both the profile scan and the connections enrichment share
    the same lookup fan-out."""
    from . import whois

    items = list(items)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(items) or 1)) as executor:
        future_to_item = {
            executor.submit(whois.lookup, item, server, authoritative, use_doh): item
            for item in items
        }
        for future in concurrent.futures.as_completed(future_to_item):
            yield future_to_item[future], future


def _cmd_whois_current_clash_profile(args, use_doh):
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
    for server, future in _whois_concurrent(servers, args.server, args.authoritative, use_doh):
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


def _connection_target(row):
    """The thing to whois for a row: the destination IP when Clash gives one
    (DIRECT connections), else the host domain — proxied connections come back
    with no IP (the proxy resolves it), so we resolve the domain ourselves."""
    return row.dest_ip or row.host


def _enrich_targets(targets, cache=None, progress=False):
    """Resolve + label each target concurrently, reusing the whois machinery.
    A target is a destination IP (whois'd directly) or a domain (DoH-resolved
    then whois'd). Returns {target: (resolved_ip, "Operator (CC)")}.

    With `progress=True`, per-target `[i/N]` lines go to stderr as each lookup
    completes — DoH+whois is slow, and without it a one-shot `--whois` run looks
    frozen. The watch loop leaves it off (its redraw is the feedback).

    Successful results are memoised in `cache` — operator/IP don't change over a
    session, so a watch loop resolves each target once instead of every tick.
    Failed/empty lookups are left uncached so a later tick retries them."""
    from . import whois

    cache = cache if cache is not None else {}
    todo = [t for t in targets if t and t not in cache]
    if not todo:
        return cache
    total = len(todo)
    if progress:
        print(f"解析 {total} 个目标的运营商 (whois, 较慢)…", file=sys.stderr)
    for done, (target, future) in enumerate(_whois_concurrent(todo, "1.1.1.1", False, True), 1):
        if progress:
            print(f"  [{done}/{total}] {target}", file=sys.stderr)
        try:
            results = future.result()
        except Exception:  # noqa: BLE001 - transient failure: stay uncached so it retries
            continue
        # Only cache successful lookups. An empty/failed result is left uncached
        # (shows blank this tick) so a later watch tick can retry it, rather than
        # pinning a transient DoH/whois failure as a permanent blank for the session.
        if results:
            res = results[0]
            cache[target] = (res.ip, whois.format_operator(res.operator, res.country))
    return cache


def _format_connections(rows, enrich=None, total=None, aggregated=False):
    """Build the connection table as a list of lines (printed by the caller, so
    the watch loop can redraw it in place)."""
    if aggregated and total is not None:
        lines = [f"活动连接: {total} → {len(rows)} 组 (host+node)"]
    else:
        lines = [f"活动连接: {len(rows)}"]
    if not rows:
        return lines
    info = enrich or {}

    # (header, value-getter) for each column, built to match the active options.
    cols = [("HOST", lambda r: r.host), ("NODE", lambda r: r.node)]
    if enrich is not None:
        cols.append(("IP", lambda r: info.get(_connection_target(r), ("", ""))[0]))
        cols.append(("OPERATOR", lambda r: info.get(_connection_target(r), ("", ""))[1]))
    if aggregated:
        cols.append(("CONNS", lambda r: str(r.count)))
    cols.append(("RULE", lambda r: r.rule))

    # Pad every column except the last (RULE) to its widest value.
    widths = [max([len(get(r)) for r in rows] + [len(head)]) for head, get in cols[:-1]]

    def fmt(values):
        padded = [f"{v:<{w}}" for v, w in zip(values[:-1], widths, strict=True)]
        padded.append(values[-1])
        return "  ".join(padded)

    lines.append(fmt([head for head, _ in cols]))
    lines.extend(fmt([get(row) for _, get in cols]) for row in rows)
    return lines


def _watch_connections(render, interval):
    """Refresh `render()` (a callable returning the table lines) every `interval`
    seconds, top-style: redraws in place (no full-screen clear → no flicker) and
    quits on 'q' or Ctrl-C. os._exit avoids joining --whois worker threads that may
    still be in a `whois`/`dig` subprocess (joining them is what made Ctrl-C hang);
    the terminal (cooked mode + cursor) is restored first. Non-TTY stdin (piped)
    falls back to a plain reprint loop with Ctrl-C only."""
    import select

    interactive = sys.stdin.isatty()
    old_term = None
    fd = -1
    if interactive:
        try:
            import termios

            fd = sys.stdin.fileno()
            old_term = termios.tcgetattr(fd)
        except Exception:  # noqa: BLE001 - no termios (e.g. Windows) -> Ctrl-C only
            interactive = False

    def restore():
        if interactive:
            sys.stdout.write("\033[?25h")  # show cursor again
            sys.stdout.flush()
        if old_term is not None:
            import termios

            termios.tcsetattr(fd, termios.TCSADRAIN, old_term)

    def quit_now(*_):
        restore()
        os._exit(0)

    signal.signal(signal.SIGINT, quit_now)
    try:
        if interactive:
            import tty

            tty.setcbreak(fd)
            sys.stdout.write("\033[2J\033[?25l")  # clear once, hide cursor
        while True:
            lines = render()
            if not interactive:
                print("\n".join(lines))
                time.sleep(interval)
                continue
            # Home, rewrite each line clearing to its end (\033[K), then clear any
            # leftover rows below from a previous, longer frame (\033[J).
            frame = (
                "\033[H"
                + "".join(f"{line}\033[K\n" for line in (*lines, "", "(q 退出)"))
                + "\033[J"
            )
            sys.stdout.write(frame)
            sys.stdout.flush()
            ready, _, _ = select.select([sys.stdin], [], [], interval)
            if ready:
                ch = sys.stdin.read(1)
                # "" means EOF (terminal detached / closed) — quit instead of
                # busy-looping, since select would keep reporting stdin readable.
                if not ch or ch in ("q", "Q"):
                    return 0
    finally:
        restore()


def cmd_connections(argv):
    """List the current Clash active connections (host/SNI → outbound node)."""
    p = argparse.ArgumentParser(
        prog="net-auto-switch connections",
        description="列出当前 Clash 活动连接 (域名/SNI → 出口节点)",
    )
    p.add_argument("--config", default=None, help="Path to config.toml")
    p.add_argument(
        "--whois",
        action="store_true",
        help="标注目标的 IP / 运营商 / 国家 (有 IP 用 IP, 走代理的按域名 DoH 解析; 较慢)",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="逐条列出 (默认按 host+node 聚合并显示连接数)",
    )
    p.add_argument(
        "-w",
        "--watch",
        nargs="?",
        const=2.0,
        type=float,
        default=None,
        metavar="SECONDS",
        help="实时刷新 (默认每 2 秒), 按 q 或 Ctrl-C 退出",
    )
    args = p.parse_args(argv)

    try:
        clash_cfg = _resolve_whois_clash_config(args.config)
    except ConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    controller = ClashController(clash_cfg)
    enrich_cache: dict[str, tuple[str, str]] = {}

    def render_lines(progress=False):
        raw_rows = summarize_connections(controller.get_connections())
        rows = raw_rows if args.raw else aggregate_connections(raw_rows)
        targets = {_connection_target(r) for r in rows}
        enrich = _enrich_targets(targets, enrich_cache, progress) if args.whois else None
        return _format_connections(rows, enrich, total=len(raw_rows), aggregated=not args.raw)

    if args.watch is None:
        print("\n".join(render_lines(progress=True)))  # one-shot: show whois progress
        return 0
    return _watch_connections(render_lines, args.watch)


def _node_note(name_cc, entry_cc, exit_cc, with_exit):
    """Pure: annotate the relationship between the name-recognized country, the
    entry (relay) country, and the probed exit country.

    With an exit probe: flags a relay (entry≠exit) and whether the name matches
    the real exit (名实相符/不符). Without a probe we can't know the true exit, so
    we only note when the entry country differs from the name (possible relay)."""
    parts = []
    if with_exit:
        if entry_cc and exit_cc and entry_cc != exit_cc:
            parts.append(f"中转 {entry_cc}→{exit_cc}")
        if name_cc and exit_cc:
            parts.append("名实相符" if name_cc == exit_cc else f"名实不符(名{name_cc}/实{exit_cc})")
    elif name_cc and entry_cc and name_cc != entry_cc:
        parts.append(f"入口在{entry_cc}(或为中转)")
    return " ".join(parts)


def _format_nodes(title, rows, with_exit):
    """Build the node table as a list of lines. Pure. Each row is a dict with
    name/region/entry/note (and exit when with_exit). REGION is the
    name-recognized country[/city], ENTRY the whois operator(country) of the
    node's server, NOTE the consistency annotation."""
    lines = [title]
    if not rows:
        lines.append("(no nodes)")
        return lines
    cols = [
        ("NAME", lambda r: r["name"]),
        ("REGION", lambda r: r["region"]),
        ("ENTRY", lambda r: r["entry"]),
    ]
    if with_exit:
        cols.append(("EXIT", lambda r: r.get("exit", "")))
    cols.append(("NOTE", lambda r: r.get("note", "")))
    widths = [max([len(get(r)) for r in rows] + [len(head)]) for head, get in cols[:-1]]

    def fmt(values):
        padded = [f"{v:<{w}}" for v, w in zip(values[:-1], widths, strict=True)]
        padded.append(values[-1])
        return "  ".join(padded)

    lines.append(fmt([head for head, _ in cols]))
    lines.extend(fmt([get(row) for _, get in cols]) for row in rows)
    return lines


def cmd_nodes(argv):
    """List proxy nodes with their recognized region + entry operator/country,
    and (with --probe) their probed exit operator/country."""
    from . import geo, whois

    p = argparse.ArgumentParser(
        prog="net-auto-switch nodes",
        description="列出节点: 识别地区 + 入口运营商/国家; --probe 额外探测出口",
    )
    p.add_argument("--config", default=None, help="Path to config.toml")
    p.add_argument(
        "--probe",
        action="store_true",
        help="额外探测每个节点出口的国家/运营商 (慢, 会逐个切换节点, 结束后恢复原节点)",
    )
    p.add_argument("--limit", type=int, default=None, help="只处理前 N 个节点")
    args = p.parse_args(argv)

    try:
        clash_cfg = _resolve_whois_clash_config(args.config)
        profile = _load_clash_api_profile(clash_cfg)
    except (ConfigError, WhoisProfileError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    nodes = profile["nodes"]
    if args.limit is not None:
        nodes = nodes[: max(0, args.limit)]

    # ENTRY: whois each unique server concurrently (network-bound; progress to stderr).
    servers = _unique_servers(nodes)
    lookup_by_server = {}
    total = len(servers)
    done = 0
    print(f"待解析 server 数 (去重后): {total}", file=sys.stderr)
    for server, future in _whois_concurrent(servers, "1.1.1.1", False, True):
        try:
            lookup_by_server[server] = future.result()
        except Exception:  # noqa: BLE001 - one bad server shouldn't abort the scan
            lookup_by_server[server] = []
        done += 1
        print(f"[{done}/{total}] {server}", file=sys.stderr)

    def entry_info(server):
        """(country_code, 'Operator (CC)') for a node's server, ('', '解析失败') on miss."""
        results = lookup_by_server.get(server) or []
        if not results:
            return "", "解析失败"
        res = results[0]
        return (res.country or ""), whois.format_operator(res.operator, res.country)

    rows = []
    for n in nodes:
        name_cc = geo.locate_by_name(n["name"]).country or ""
        entry_cc, entry = entry_info(n["server"])
        rows.append(
            {
                "name": n["name"],
                "region": geo.region_label(n["name"]),
                "entry": entry,
                "_name_cc": name_cc,
                "_entry_cc": entry_cc,
                "_exit_cc": "",
            }
        )

    with_exit = args.probe
    if args.probe:
        controller = ClashController(clash_cfg)
        try:
            proxies = controller.get_proxies()
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 无法读取 Clash 节点, 跳过出口探测: {e}", file=sys.stderr)
            proxies = {}
        group = controller.resolve_managed_group(proxies) if proxies else None
        if not group or group not in proxies:
            print("⚠ 无法确定要管理的代理组, 跳过出口探测", file=sys.stderr)
            with_exit = False
        else:
            if controller.is_tun_enabled():
                print(
                    "⚠ 检测到 TUN 模式开启:--probe 会逐个切换当前节点,"
                    "在 TUN 下这会重路由【全部】系统流量(不只代理应用)。\n"
                    "  建议先在 Clash Verge 关闭 TUN(虚拟网卡)再跑 —— 更稳, 也不会打断其它应用。",
                    file=sys.stderr,
                )
            original = proxies[group].get("now")
            print(
                f"探测出口中 (会切换 '{group}', {len(nodes)} 个节点; 结束后恢复 '{original}')…",
                file=sys.stderr,
            )
            for i, row in enumerate(rows):
                country, operator = controller.probe_exit(nodes[i]["name"], group)
                row["_exit_cc"] = country
                row["exit"] = whois.format_operator(operator, country) if operator else "探测失败"
                print(f"[{i + 1}/{len(rows)}] {nodes[i]['name']} -> {row['exit']}", file=sys.stderr)
            if original:
                controller.switch_proxy(original, group)
                print(f"已恢复 '{group}' -> '{original}'", file=sys.stderr)

    for row in rows:
        row["note"] = _node_note(row["_name_cc"], row["_entry_cc"], row["_exit_cc"], with_exit)

    title = f"=== [{profile['name']}] 节点数: {len(rows)} ==="
    print("\n".join(_format_nodes(title, rows, with_exit)))
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
    if argv and argv[0] == "connections":
        sys.exit(cmd_connections(argv[1:]))
    if argv and argv[0] == "nodes":
        sys.exit(cmd_nodes(argv[1:]))
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
