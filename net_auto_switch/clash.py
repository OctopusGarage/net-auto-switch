import logging
import os
import re
import subprocess
import time

import requests

log = logging.getLogger("net_auto_switch.clash")

DEAD = 9999

GROUP_NAMES = {
    "SG": "新加坡",
    "Tokyo": "日本东京",
    "JP_Other": "日本其他地区",
}


class ClashController:
    def __init__(self, cfg):
        self.cfg = cfg
        self.headers = {"Authorization": f"Bearer {cfg.secret}"}
        self.sg_re = re.compile(cfg.patterns.sg, re.IGNORECASE)
        self.jp_re = re.compile(cfg.patterns.jp, re.IGNORECASE)
        self.tokyo_re = re.compile(cfg.patterns.tokyo, re.IGNORECASE)
        self.trial_re = re.compile(cfg.patterns.trial)
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

    def switch_proxy(self, node):
        r = requests.put(
            f"{self.cfg.api}/proxies/GLOBAL",
            headers=self.headers,
            json={"name": node},
            timeout=5,
        )
        return r.status_code == 204

    def test_all_delays(self, node_list):
        delays = {}
        for node in node_list:
            d = self.test_delay(node)
            delays[node] = d
            log.info(f"Delay test {node} -> {d} ms")
        return delays

    # ----- grouping -----
    def classify_node(self, name):
        if self.sg_re.search(name):
            return "SG"
        if self.jp_re.search(name):
            if self.tokyo_re.search(name):
                return "Tokyo"
            return "JP_Other"
        return None

    def get_all_nodes_by_group(self, proxies):
        groups = {"SG": [], "Tokyo": [], "JP_Other": []}
        for name, data in proxies.items():
            if data["type"] in ("Selector", "URLTest", "Fallback"):
                continue
            if self.trial_re.search(name):
                continue
            group = self.classify_node(name)
            if group and name not in groups[group]:
                groups[group].append(name)
        return groups

    def get_node_region(self, node_name):
        try:
            self.switch_proxy(node_name)
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

    def enrich_tokyo_via_ip(self, groups):
        jp_others = groups["JP_Other"]
        if not jp_others:
            return
        log.info("No Tokyo node by name, checking via IP location...")
        check_count = min(len(jp_others), 10)
        for i, node in enumerate(jp_others[:check_count], 1):
            log.info(f"  [{i}/{check_count}] Checking {node}...")
            region = self.get_node_region(node)
            if region and region.lower() == "tokyo":
                log.info(f"  -> {node} is Tokyo")
                groups["Tokyo"].append(node)
                groups["JP_Other"].remove(node)
            time.sleep(0.3)

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
            log.info(f"{GROUP_NAMES.get(g, g)} nodes: {len(groups.get(g, []))}")

        if not groups["Tokyo"] and not dry_run:
            self.enrich_tokyo_via_ip(groups)

        current = proxies["GLOBAL"]["now"]
        current_group = next(
            (g for g in self.cfg.group_priority if current in groups.get(g, [])), None
        ) or self.classify_node(current)
        group_label = GROUP_NAMES.get(current_group, current_group)
        log.info(f"Current node: {current} (group: {group_label})")

        all_nodes = []
        for g in self.cfg.group_priority:
            for n in groups.get(g, []):
                if n not in all_nodes:
                    all_nodes.append(n)
        if not all_nodes:
            log.info("No SG/Tokyo/JP_Other nodes found")
            return False

        delays = self.test_all_delays(all_nodes)
        should_switch, target = self.select_node(current, current_group, groups, delays)

        all_dead = not any(delays.get(n, DEAD) < DEAD for n in all_nodes)
        if not should_switch and all_dead:
            log.warning("All nodes unreachable, trying profile switch...")
            profiles, current_uid = self.get_profiles()
            for p in profiles:
                if p.get("uid") != current_uid:
                    name = p.get("name") or p.get("uid")
                    if not dry_run and self.switch_profile_by_name(name):
                        log.info("Profile switched, will retry next cycle")
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
            elif self.switch_proxy(target):
                self._switch_times.append(now)
                log.info(f"Switched to {target}")
            else:
                log.error("Switch failed")
        else:
            log.info("No switch needed")
        return False
