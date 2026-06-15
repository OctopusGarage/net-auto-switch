import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass

import requests

log = logging.getLogger("net_auto_switch.clash")

DEAD = 9999


@dataclass(frozen=True)
class ConnectionRow:
    """One row of `get_connections()`, reduced to what a human cares about:
    which host is being reached, through which outbound node, by which rule."""

    host: str  # domain / SNI; falls back to the destination IP when absent
    dest_ip: str
    dest_port: str
    node: str  # the actual outbound node (chains[0]); "?" when unknown
    rule: str  # rule, with payload appended as "rule(payload)"
    network: str


def summarize_connections(connections):
    """Pure transform of the Clash `/connections` list into sorted ConnectionRows.
    I/O-free so it stays unit-testable; the CLI does the HTTP + printing."""
    rows = []
    for conn in connections:
        md = conn.get("metadata") or {}
        dest_ip = md.get("destinationIP") or ""
        host = md.get("host") or md.get("sniffHost") or dest_ip
        chains = conn.get("chains") or []
        node = chains[0] if chains else "?"
        rule = conn.get("rule") or ""
        payload = conn.get("rulePayload") or ""
        if payload:
            rule = f"{rule}({payload})" if rule else payload
        rows.append(
            ConnectionRow(
                host=host,
                dest_ip=dest_ip,
                dest_port=md.get("destinationPort") or "",
                node=node,
                rule=rule,
                network=(md.get("network") or "").lower(),
            )
        )
    rows.sort(key=lambda r: (r.host, r.node))
    return rows


@dataclass(frozen=True)
class ConnectionGroup:
    """Per-connection rows folded by (host, node), with a count of how many
    connections share that pair."""

    host: str
    node: str
    count: int
    dest_ip: str
    rule: str
    network: str


def aggregate_connections(rows):
    """Fold ConnectionRows by (host, node), counting duplicates. Keeps the first
    non-empty destination IP / rule seen. Sorted by host then node, matching the
    per-connection view."""
    acc = {}
    for r in rows:
        key = (r.host, r.node)
        a = acc.setdefault(key, {"count": 0, "dest_ip": "", "rule": "", "network": r.network})
        a["count"] += 1
        if not a["dest_ip"]:
            a["dest_ip"] = r.dest_ip
        if not a["rule"]:
            a["rule"] = r.rule
    groups = [
        ConnectionGroup(
            host=host,
            node=node,
            count=a["count"],
            dest_ip=a["dest_ip"],
            rule=a["rule"],
            network=a["network"],
        )
        for (host, node), a in acc.items()
    ]
    groups.sort(key=lambda g: (g.host, g.node))
    return groups


class ClashController:
    def __init__(self, cfg, notify=False):
        self.cfg = cfg
        self.notify = notify
        self.headers = {"Authorization": f"Bearer {cfg.secret}"}
        # name -> compiled regex, in config order (first match wins).
        self.region_res = {n: re.compile(rx, re.IGNORECASE) for n, rx in cfg.regions.items()}
        self.trial_re = re.compile(cfg.trial)
        self._switch_times = []
        self._profile_switch_times = []

    # ----- API -----
    def get_proxies(self):
        r = requests.get(f"{self.cfg.api}/proxies", headers=self.headers, timeout=5)
        return r.json()["proxies"]

    def test_delay(self, node):
        try:
            r = requests.get(
                f"{self.cfg.api}/proxies/{node}/delay",
                headers=self.headers,
                params={"url": "http://www.gstatic.com/generate_204", "timeout": 3000},
                timeout=5,
            )
            delay = r.json()["delay"]
            return delay if delay > 0 else DEAD
        except Exception:
            return DEAD

    def switch_proxy(self, node, group):
        r = requests.put(
            f"{self.cfg.api}/proxies/{group}",
            headers=self.headers,
            json={"name": node},
            timeout=5,
        )
        return r.status_code == 204

    def get_mode(self):
        try:
            r = requests.get(f"{self.cfg.api}/configs", headers=self.headers, timeout=5)
            return r.json().get("mode")
        except Exception as e:
            log.warning(f"Failed to read Clash mode: {e}")
            return None

    def get_connections(self):
        try:
            r = requests.get(f"{self.cfg.api}/connections", headers=self.headers, timeout=5)
            return r.json().get("connections") or []
        except Exception as e:
            log.warning(f"Failed to read Clash connections: {e}")
            return []

    def test_all_delays(self, node_list):
        delays = {}
        for node in node_list:
            d = self.test_delay(node)
            delays[node] = d
            log.info(f"Delay test {node} -> {d} ms")
        return delays

    # ----- grouping -----
    def classify_node(self, name):
        for region, rx in self.region_res.items():
            if rx.search(name):
                return region
        return None

    def get_all_nodes_by_group(self, proxies):
        groups = {name: [] for name in self.region_res}
        for name, data in proxies.items():
            if data["type"] in ("Selector", "URLTest", "Fallback"):
                continue
            if self.trial_re.search(name):
                continue
            group = self.classify_node(name)
            if group and name not in groups[group]:
                groups[group].append(name)
        return groups

    def get_node_region(self, node_name, group):
        try:
            self.switch_proxy(node_name, group)
            time.sleep(0.5)
            proxies_cfg = {
                "http": f"http://127.0.0.1:{self.cfg.proxy_port}",
                "https": f"http://127.0.0.1:{self.cfg.proxy_port}",
            }
            r = requests.get("https://ipwhois.app/json/", proxies=proxies_cfg, timeout=10)
            return r.json().get("region", "")
        except Exception as e:
            log.warning(f"Location check error: {e}")
            return ""

    def get_exit_operator(self):
        """Best-effort label for the egress IP's operator, via the local proxy.

        Reuses the ipwhois.app probe (same plumbing as get_node_region) and maps
        its isp/org through whois.OPERATOR_HINTS for a friendly label like
        'AWS (US)'. Returns '' on any failure. This is an IP-probe side effect,
        so callers must only use it after a real switch (never in dry-run, see
        ADR-0003).
        """
        from . import whois

        try:
            proxies_cfg = {
                "http": f"http://127.0.0.1:{self.cfg.proxy_port}",
                "https": f"http://127.0.0.1:{self.cfg.proxy_port}",
            }
            r = requests.get("https://ipwhois.app/json/", proxies=proxies_cfg, timeout=10)
            j = r.json()
            isp = j.get("isp") or ""
            org = j.get("org") or ""
            operator = whois.match_operator(f"{isp} {org}") or isp or org or "unknown"
            country = j.get("country_code") or ""
            return f"{operator} ({country})" if country else operator
        except Exception as e:
            log.warning(f"Exit operator check error: {e}")
            return ""

    def enrich_via_ip(self, groups, group):
        """Reclassify `source` nodes whose IP geolocates to `match` into `target`.

        Config-driven via cfg.ip_enrich; a no-op if it's unset or its regions
        aren't present (e.g. a US-only setup with no Tokyo region). Probes by
        temporarily pointing `group` (the managed group) at each candidate.
        """
        ie = self.cfg.ip_enrich or {}
        target, source = ie.get("target"), ie.get("source")
        match = (ie.get("match") or "").lower()
        if not match or target not in groups or source not in groups:
            return
        candidates = groups[source]
        if not candidates:
            return
        log.info(f"No {target} node by name, checking {source} via IP location...")
        check_count = min(len(candidates), 10)
        for i, node in enumerate(candidates[:check_count], 1):
            log.info(f"  [{i}/{check_count}] Checking {node}...")
            region = self.get_node_region(node, group)
            if region and region.lower() == match:
                log.info(f"  -> {node} is {target}")
                groups[target].append(node)
                groups[source].remove(node)
            time.sleep(0.3)

    # ----- managed group resolution -----
    def detect_entry_group(self, proxies):
        """The Selector group most live connections enter through.

        Each connection's `chains` runs node-first to entry-group-last, so the
        last element is the group the rules routed it to. Returns the busiest
        such Selector, or None when there are no proxied connections to learn from.
        """
        counts = {}
        for c in self.get_connections():
            chain = c.get("chains") or []
            if len(chain) < 2:
                continue  # DIRECT / direct node — no proxy group involved
            entry = chain[-1]
            g = proxies.get(entry)
            if g and g.get("type") == "Selector":
                counts[entry] = counts.get(entry, 0) + 1
        if not counts:
            return None
        return max(counts, key=lambda name: counts[name])

    def resolve_managed_group(self, proxies):
        """Pick the proxy group to read + switch, or None to skip this cycle.

        An explicit cfg.managed_group (anything but "auto") always wins. Otherwise
        resolve by Clash mode: global -> GLOBAL; direct -> skip; rule -> the entry
        group most live connections use, falling back to GLOBAL with a warning.
        """
        override = self.cfg.managed_group
        if override and override != "auto":
            return override
        mode = self.get_mode()
        if mode == "global":
            return "GLOBAL"
        if mode == "direct":
            log.info("Clash in direct mode — no proxy to manage, skipping cycle.")
            return None
        entry = self.detect_entry_group(proxies)
        if entry:
            log.info(f"Rule mode: managing '{entry}' (busiest entry group in live connections)")
            return entry
        log.warning(
            f"Rule mode but no entry group detected from connections (mode={mode}); "
            "falling back to GLOBAL."
        )
        return "GLOBAL"

    # ----- selection -----
    def select_best_in_group(self, group_nodes, delays):
        if not group_nodes:
            return None
        available = [n for n in group_nodes if delays.get(n, DEAD) < DEAD]
        if not available:
            return None
        return min(available, key=lambda n: delays.get(n, DEAD))

    def select_node(self, current, current_group, groups, delays):
        current_delay = delays.get(current, DEAD)
        if current_delay <= self.cfg.delay_limit:
            return False, None
        best_in_current = self.select_best_in_group(groups.get(current_group, []), delays)
        if best_in_current:
            return True, best_in_current
        for group in self.cfg.group_priority:
            if group == current_group:
                continue
            best = self.select_best_in_group(groups.get(group, []), delays)
            if best:
                return True, best
        return False, None

    # ----- profile fallback -----
    def get_profiles(self):
        try:
            import yaml

            with open(os.path.expanduser(self.cfg.profiles_yaml)) as f:
                data = yaml.safe_load(f)
            items = data.get("items", [])
            profiles = [p for p in items if p.get("type") == "remote"]
            return profiles, data.get("current")
        except Exception as e:
            log.error(f"Failed to read profiles.yaml: {e}")
            return [], None

    def switch_profile_by_name(self, name):
        now = time.time()
        self._profile_switch_times = [t for t in self._profile_switch_times if now - t < 1800]
        if len(self._profile_switch_times) >= self.cfg.max_profile_switch_per_30min:
            log.info("Profile switch limit reached (per 30min)")
            return False
        script = f'''
tell application "Clash Verge"
    activate
end tell
delay 0.5
tell application "System Events"
    tell process "Clash Verge"
        click button "Profiles" of group 3 of group 2 of UI element 1 of scroll area 1 of group 1 of group 1 of window 1
        delay 0.8
        click UI element "{name}" of UI element 1 of scroll area 1 of group 1 of group 1 of window 1
    end tell
end tell
'''
        try:
            result = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=15)
            if result.returncode != 0:
                log.error(f"AppleScript error: {result.stderr.decode().strip()}")
                return False
            log.info(f"Profile switched to [{name}] via UI")
            self._profile_switch_times.append(now)
            return True
        except subprocess.TimeoutExpired:
            log.error("AppleScript timeout")
            return False
        except Exception as e:
            log.error(f"AppleScript failed: {e}")
            return False

    # ----- one full cycle -----
    def run_cycle(self, dry_run=False):
        """Run one Clash check/switch cycle. Returns True if a profile fallback occurred."""
        proxies = self.get_proxies()
        log.info(f"Total proxies detected: {len(proxies)}")

        groups = self.get_all_nodes_by_group(proxies)
        for g in self.cfg.group_priority:
            log.info(f"{g} nodes: {len(groups.get(g, []))}")

        group = self.resolve_managed_group(proxies)
        if group is None:
            return False
        if group not in proxies:
            selectors = [n for n, d in proxies.items() if d.get("type") == "Selector"]
            log.error(
                f"Managed group '{group}' not found in Clash (available selectors: {selectors}). "
                f"Set clash.managed_group to the group your rules route through."
            )
            return False

        enrich_target = (self.cfg.ip_enrich or {}).get("target")
        if enrich_target and not groups.get(enrich_target) and not dry_run:
            self.enrich_via_ip(groups, group)

        current = proxies[group]["now"]
        current_group = next(
            (g for g in self.cfg.group_priority if current in groups.get(g, [])), None
        ) or self.classify_node(current)
        log.info(f"Current node: {current} (group: {current_group})")

        all_nodes = []
        for g in self.cfg.group_priority:
            for n in groups.get(g, []):
                if n not in all_nodes:
                    all_nodes.append(n)
        if not all_nodes:
            log.info("No nodes matched any configured region")
            return False

        delays = self.test_all_delays(all_nodes)
        should_switch, target = self.select_node(current, current_group, groups, delays)

        all_dead = not any(delays.get(n, DEAD) < DEAD for n in all_nodes)
        if not should_switch and all_dead and sys.platform != "darwin":
            # Profile fallback drives Clash Verge via AppleScript UI automation,
            # which is macOS-only; elsewhere there's nothing more to try this cycle.
            log.warning("All nodes unreachable; profile fallback is macOS-only, skipping.")
            return False
        if not should_switch and all_dead:
            log.warning("All nodes unreachable, trying profile switch...")
            profiles, current_uid = self.get_profiles()
            for p in profiles:
                if p.get("uid") != current_uid:
                    name = p.get("name") or p.get("uid")
                    if not dry_run and self.switch_profile_by_name(name):
                        log.info("Profile switched, will retry next cycle")
                        if self.notify:
                            from . import notify

                            notify.send("📑 订阅已切换", name, "所有节点不可用,已回退订阅")
                        return True
                    if dry_run:
                        log.info(f"[DRY-RUN] Would switch profile to {name}")
                        return False
            log.info("No other profiles available")
            return False

        now = time.time()
        self._switch_times = [t for t in self._switch_times if now - t < 60]
        if should_switch and target and target != current:
            if len(self._switch_times) >= self.cfg.max_switch_per_min:
                log.info("Switch limit reached (per minute)")
            elif dry_run:
                log.info(f"[DRY-RUN] Would switch to {target}")
            elif self.switch_proxy(target, group):
                self._switch_times.append(now)
                operator = self.get_exit_operator()
                log.info(f"Switched to {target}" + (f" (exit: {operator})" if operator else ""))
                if self.notify:
                    from . import notify

                    notify.send(
                        "🔀 代理节点已切换", target, f"出口: {operator}" if operator else ""
                    )
            else:
                log.error("Switch failed")
        else:
            log.info("No switch needed")
        return False
