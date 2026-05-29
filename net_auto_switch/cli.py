import argparse
import logging
import logging.handlers
import os
import sys

from .config import ConfigError, load_config
from .orchestrator import Orchestrator

log = logging.getLogger("net_auto_switch.cli")

LOG_PATH = os.path.expanduser("~/Library/Logs/net_auto_switch.log")
LOG_BACKUP_DAYS = 14


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


def main(argv=None):
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
