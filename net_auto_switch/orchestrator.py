import logging
import time

import requests

from . import wifi as wifi_mod
from .clash import ClashController

log = logging.getLogger("net_auto_switch.orchestrator")


class Orchestrator:
    def __init__(self, cfg, dry_run=False):
        self.cfg = cfg
        self.dry_run = dry_run
        self.clash = ClashController(cfg.clash, notify=cfg.notify)
        self.last_wifi_check = 0.0
        self.last_wifi_switch = 0.0

    def _wifi_due(self, now, last_check):
        if last_check <= 0.0:
            return True
        return now - last_check >= self.cfg.wifi.check_interval

    def _cooldown_ok(self, now, last_switch):
        return now - last_switch >= self.cfg.wifi.switch_cooldown

    def _maybe_wifi(self, now):
        if not self._wifi_due(now, self.last_wifi_check):
            return
        self.last_wifi_check = now
        wcfg = self.cfg.wifi
        current = wifi_mod.get_current_wifi(wcfg.interface)
        lat, loss = wifi_mod.ping_host()
        log.info(f"Current WiFi: {current} latency={lat}ms loss={loss}%")
        if not wifi_mod.is_bad_network(lat, loss, wcfg.bad_latency_ms, wcfg.bad_loss_pct):
            log.info("WiFi is fine.")
            return
        if not self._cooldown_ok(now, self.last_wifi_switch):
            log.info("WiFi bad but in switch cooldown, skipping.")
            return
        candidates = wifi_mod.candidate_wifis(wcfg.interface)
        log.info(f"Candidate WiFis: {candidates}")
        if not candidates:
            log.info("No candidate WiFis.")
            return
        best, best_lat = wifi_mod.find_best_wifi(candidates)
        if best is None or lat is None or best_lat is None:
            log.info("Cannot determine a better WiFi.")
            return
        improvement = lat - best_lat
        if improvement >= wcfg.min_improvement_ms:
            if wifi_mod.switch_to(best, wcfg.interface, dry_run=self.dry_run):
                self.last_wifi_switch = now
                if self.cfg.notify and not self.dry_run:
                    from . import notify

                    notify.send("📶 WiFi 已切换", best, f"延迟 {best_lat}ms")
        else:
            log.info(f"Improvement {improvement}ms below threshold, not switching.")

    def run_once(self, now=None):
        now = now if now is not None else time.time()
        marker = " [dry-run]" if self.dry_run else ""
        log.info(f"===== cycle start{marker} =====")
        if self.cfg.wifi.enabled:
            try:
                self._maybe_wifi(now)
            except Exception:
                log.exception("WiFi step failed")
        else:
            log.debug("WiFi layer disabled")
        try:
            self.clash.run_cycle(dry_run=self.dry_run)
        except requests.RequestException as e:
            log.error(f"Clash API error: {e}")
        except Exception:
            log.exception("Clash step failed")

    def run_forever(self):
        log.info("net-auto-switch started. Ctrl+C to stop.")
        try:
            while True:
                self.run_once()
                log.info(f"Next check in {self.cfg.main_interval}s")
                time.sleep(self.cfg.main_interval)
        except KeyboardInterrupt:
            log.info("Shutting down gracefully.")
