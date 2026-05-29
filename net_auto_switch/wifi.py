import re
import subprocess
import logging

log = logging.getLogger("net_auto_switch.wifi")


def get_current_wifi(interface="en0"):
    result = subprocess.run(
        ["networksetup", "-getairportnetwork", interface],
        capture_output=True, text=True,
    )
    output = result.stdout.strip()
    if "You are not associated" in output:
        return None
    match = re.search(r"Current Air Port network: (.+)", output)
    return match.group(1) if match else None


def ping_host(host="8.8.8.8", count=3):
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-m", "2", host],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        log.warning("ping timed out")
        return None, None
    output = result.stdout
    avg_match = re.search(r"round-trip min/avg/max/stddev = .+?/(.+?)/", output)
    latency = float(avg_match.group(1)) if avg_match else None
    loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    loss = float(loss_match.group(1)) if loss_match else None
    return latency, loss


def known_wifis(interface="en0"):
    result = subprocess.run(
        ["networksetup", "-listpreferredwirelessnetworks", interface],
        capture_output=True, text=True,
    )
    lines = result.stdout.strip().split("\n")
    names = []
    for line in lines[1:]:
        line = line.strip()
        if line:
            names.append(line)
    return names


def available_wifis():
    result = subprocess.run(
        ["system_profiler", "SPAirPortDataType"],
        capture_output=True, text=True,
    )
    wifis = set()
    in_other_networks = False
    for line in result.stdout.split("\n"):
        if "Other Local Wi-Fi Networks:" in line:
            in_other_networks = True
            continue
        if in_other_networks:
            stripped = line.strip()
            if (
                stripped.endswith(":")
                and not stripped.startswith("PHY ")
                and not stripped.startswith("Channel")
            ):
                name = stripped.rstrip(":").strip()
                # Heuristic ported from the original script: SSIDs with spaces are
                # skipped because parsed system_profiler lines with spaces are
                # usually metadata, not network names. May miss spaced SSIDs.
                if name and " " not in name and not name.startswith("Signal"):
                    wifis.add(name)
            if "Current Network Information" in line:
                break
    return wifis


def candidate_wifis(interface="en0"):
    known = set(known_wifis(interface))
    available = available_wifis()
    return list(known & available)


def is_bad_network(lat, loss, bad_latency, bad_loss):
    if lat is None or loss is None:
        return True
    return lat > bad_latency or loss > bad_loss


def find_best_wifi(candidates):
    """Ping-test candidates, return (name, latency) of lowest latency or (None, None)."""
    best = None
    best_lat = None
    for w in candidates:
        log.info(f"Testing WiFi: {w}")
        lat, loss = ping_host()
        log.info(f"  latency: {lat}ms, loss: {loss}%")
        if lat is None:
            continue
        if best_lat is None or lat < best_lat:
            best = w
            best_lat = lat
    return best, best_lat


def switch_to(wifi_name, interface="en0", dry_run=False):
    if dry_run:
        log.info(f"[DRY-RUN] Would switch to {wifi_name}")
        return True
    log.info(f"Switching to WiFi: {wifi_name}")
    result = subprocess.run(
        ["networksetup", "-setairportnetwork", interface, wifi_name],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        log.info(f"Successfully switched to {wifi_name}")
    else:
        log.error(f"Failed to switch to {wifi_name}: {result.stderr}")
    return result.returncode == 0
