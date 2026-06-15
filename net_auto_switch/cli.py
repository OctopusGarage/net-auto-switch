import argparse
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

LOG_PATH = os.path.expanduser("~/Library/Logs/net_auto_switch.log")
LOG_BACKUP_DAYS = 14

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHD_LABEL = "com.octopusgarage.net-auto-switch"
LAUNCHD_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")
INSTALL_LAUNCHD = os.path.join(PROJECT_DIR, "scripts", "install-launchd.sh")
REPO = "OctopusGarage/net-auto-switch"


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


def _download_release(tag, dest):
    """Download the (export-ignore filtered) source tarball for `tag` and extract
    it over `dest`. config.toml is gitignored, so it's absent from the archive and
    left untouched."""
    url = f"https://github.com/{REPO}/archive/refs/tags/{tag}.tar.gz"
    tmp = tempfile.mkdtemp()
    try:
        tarball = os.path.join(tmp, "release.tar.gz")
        if subprocess.run(["curl", "-fsSL", url, "-o", tarball]).returncode != 0:
            return False
        os.makedirs(dest, exist_ok=True)
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
        print("✗ net-auto-switch is macOS-only (it relies on launchd, networksetup, AppleScript).")
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
        print(f"• Backed up existing {out} -> {backup}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_config_toml(detected, group_priority, regions))
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


def cmd_whois(argv):
    """Resolve a domain / IP to its operator or cloud provider."""
    from . import whois

    p = argparse.ArgumentParser(
        prog="net-auto-switch whois",
        description="解析域名/IP 对应的运营商",
    )
    p.add_argument("-s", "--server", default="1.1.1.1", help="指定 DNS 服务器 (默认 1.1.1.1)")
    p.add_argument("-a", "--authoritative", action="store_true",
                   help="查询域名的权威 NS, 再向该 NS 直接发起 A 查询 (隐含 --no-doh)")
    p.add_argument("--no-doh", dest="doh", action="store_false", default=True,
                   help="改用系统 DNS 解析 (默认走 Cloudflare DoH 绕开 TUN 模式劫持)")
    p.add_argument("targets", nargs="+", help="域名或 IP")
    args = p.parse_args(argv)

    # DoH is HTTPS-based; -a relies on plaintext DNS to a specific NS, so the two
    # are mutually exclusive. Asking for -a implicitly turns DoH off.
    use_doh = args.doh and not args.authoritative
    for target in args.targets:
        whois.analyze(target.strip(), args.server, args.authoritative, use_doh)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "init":
        sys.exit(cmd_init(argv[1:]))
    if argv and argv[0] == "update":
        sys.exit(cmd_update(argv[1:]))
    if argv and argv[0] == "whois":
        sys.exit(cmd_whois(argv[1:]))

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
