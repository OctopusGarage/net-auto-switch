"""Resolve a domain / IP to its operator or cloud provider.

Ported from the standalone `k_whois` script. The pure helpers
(`is_ip`, `extract_field`, `match_operator`, `guess_operator`) are kept I/O-free
so they stay unit-testable and so the daemon can reuse `match_operator` to label
a node's exit IP (see ClashController.get_exit_operator).
"""

import ipaddress
import json
import random
import subprocess
import time
from dataclasses import dataclass

OPERATOR_HINTS = [
    ("tencent.com", "腾讯云 Tencent Cloud"),
    ("qcloud", "腾讯云 Tencent Cloud"),
    ("aliyun.com", "阿里云 Alibaba Cloud"),
    ("alibaba", "阿里云 Alibaba Cloud"),
    ("huaweicloud.com", "华为云 Huawei Cloud"),
    ("huawei", "华为云 Huawei Cloud"),
    ("baidubce.com", "百度智能云 Baidu Cloud"),
    ("baidu.com", "百度 Baidu"),
    ("amazonaws.com", "AWS"),
    ("amazon.com", "AWS / Amazon"),
    ("google.com", "Google Cloud"),
    ("googleusercontent", "Google Cloud"),
    ("microsoft.com", "Microsoft Azure"),
    ("azure", "Microsoft Azure"),
    ("digitalocean", "DigitalOcean"),
    ("linode.com", "Linode / Akamai"),
    ("akamai", "Akamai"),
    ("ovh.net", "OVH"),
    ("hetzner", "Hetzner"),
    ("cloudflare.com", "Cloudflare"),
    ("oracle.com", "Oracle Cloud"),
    ("vultr", "Vultr"),
    ("ucloud", "UCloud"),
    ("kingsoft", "金山云 Kingsoft Cloud"),
    ("ksyun", "金山云 Kingsoft Cloud"),
    ("jdcloud", "京东云 JD Cloud"),
    ("chinatelecom", "中国电信 China Telecom"),
    ("chinaunicom", "中国联通 China Unicom"),
    ("chinamobile", "中国移动 China Mobile"),
    ("cnnic", "CNNIC"),
]

REGIONAL_WHOIS = {
    "ripe": "whois.ripe.net",
    "apnic": "whois.apnic.net",
    "lacnic": "whois.lacnic.net",
    "afrinic": "whois.afrinic.net",
    "arin": "whois.arin.net",
}

REGISTRY_NOISE = (
    "iana",
    "apnic",
    "ripe",
    "arin",
    "lacnic",
    "afrinic",
    "administered by",
    "not allocated",
    "reserved",
)

FALLBACK_KEYS = ("org-name", "organisation", "owner", "netname", "descr")


@dataclass(frozen=True)
class LookupResult:
    target: str
    ip: str
    operator: str
    country: str = ""


def is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def dig(args: list[str]) -> list[str]:
    out = (
        subprocess.run(
            ["dig", *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        .stdout.strip()
        .splitlines()
    )
    return [line.strip().rstrip(".") for line in out if line.strip()]


def find_authoritative_ns(domain: str, server: str) -> str | None:
    """逐级回退到父域查 NS, 取到第一个能解析的权威 NS 主机名。"""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        zone = ".".join(parts[i:])
        ns_list = [x for x in dig([f"@{server}", "+short", "NS", zone]) if x]
        if ns_list:
            return ns_list[0]
    return None


def doh_query(domain: str, qtype: str = "A") -> list[str]:
    """通过 Cloudflare DoH (HTTPS) 解析, 绕开 TUN 模式 DNS 劫持。"""
    url = f"https://1.1.1.1/dns-query?name={domain}&type={qtype}"
    proc = subprocess.run(
        ["curl", "-s", "--max-time", "10", "-H", "accept: application/dns-json", url],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    return [a.get("data", "").rstrip(".") for a in data.get("Answer", [])]


def resolve(domain: str, server: str, authoritative: bool, use_doh: bool) -> tuple[list[str], str]:
    """返回 (IP 列表, 实际使用的 DNS 服务器描述)。"""
    if use_doh:
        answers = doh_query(domain, "A")
        return [x for x in answers if is_ip(x)], "DoH(1.1.1.1)"

    used = server
    if authoritative:
        ns = find_authoritative_ns(domain, server)
        if ns:
            used = ns
        else:
            print(f"  ⚠ 未找到权威 NS, 回退到 {server}")
    ips = [x for x in dig([f"@{used}", "+short", domain]) if is_ip(x)]
    return ips, used


def _whois_one(ip: str, host: str | None, retries: int = 2) -> str:
    cmd = ["whois"]
    if host:
        cmd += ["-h", host]
    cmd.append(ip)
    for attempt in range(retries + 1):
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=15)
            out = proc.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            out = ""
        if out.strip():
            return out
        if attempt < retries:
            time.sleep(0.5 + random.random())  # backoff with jitter
    return ""


def whois_query(ip: str) -> str:
    """先查默认 whois, 若结果指向其他 RIR 则再查一次, 拼起来返回。"""
    raw = _whois_one(ip, None)
    low = raw.lower()
    extra_hosts: list[str] = []
    for key, host in REGIONAL_WHOIS.items():
        if host in low and host not in raw.split():
            continue  # already queried inline
        # 触发条件: refer/whois 行指向该 RIR, 或文本提示 transferred
        if (
            f"refer:        {host}" in raw
            or f"whois:        {host}" in raw
            or f"transferred to {key} ncc" in low
            or f"transferred to {key}" in low
        ):
            extra_hosts.append(host)

    seen = set()
    for host in extra_hosts:
        if host in seen:
            continue
        seen.add(host)
        raw += "\n" + _whois_one(ip, host)
    return raw


def extract_field(raw: str, key: str) -> str | None:
    prefix = key + ":"
    for line in raw.splitlines():
        if line.startswith("%") or line.startswith("#"):
            continue
        if line.lower().lstrip().startswith(prefix):
            value = line.split(":", 1)[1].strip()
            low = value.lower()
            if value and not any(n in low for n in REGISTRY_NOISE):
                return value
    return None


def match_operator(text: str) -> str | None:
    """Map a free-text blob (whois body, or an isp/org string) to a friendly
    operator label via OPERATOR_HINTS. Returns None when nothing matches."""
    low = text.lower()
    for needle, name in OPERATOR_HINTS:
        if needle in low:
            return name
    return None


def guess_operator(raw: str) -> str:
    hit = match_operator(raw)
    if hit:
        return hit
    for key in FALLBACK_KEYS:
        value = extract_field(raw, key)
        if value:
            return value
    return "未知"


def format_operator(operator: str, country: str = "") -> str:
    suffix = f" ({country})" if country and country.upper() not in ("ZZ", "EU") else ""
    return f"{operator}{suffix}"


def lookup(target: str, server: str, authoritative: bool, use_doh: bool) -> list[LookupResult]:
    if is_ip(target):
        ips = [target]
    else:
        ips, _ = resolve(target, server, authoritative, use_doh)
        if not ips:
            return []

    results = []
    for ip in ips:
        raw = whois_query(ip)
        operator = guess_operator(raw) if raw.strip() else "whois 无返回"
        country = extract_field(raw, "country") or ""
        results.append(LookupResult(target=target, ip=ip, operator=operator, country=country))
    return results


def analyze(target: str, server: str, authoritative: bool, use_doh: bool) -> None:
    results = lookup(target, server, authoritative, use_doh)
    if not results:
        print(f"{target}\t解析失败")
        return
    for result in results:
        label = result.ip if is_ip(target) else f"{target} → {result.ip}"
        print(f"{label}\t{format_operator(result.operator, result.country)}")
