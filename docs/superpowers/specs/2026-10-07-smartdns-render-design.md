# SmartDNS renderer design

## Goal

Extend the opt-in `dns render` command to generate a SmartDNS configuration that implements persistent local caching, domain-based upstream selection, and measured fastest-IP responses. The command generates a file only. It does not install SmartDNS, change operating-system DNS, or edit Clash Verge.

## Approaches

1. **Generate a SmartDNS configuration (chosen).** SmartDNS already implements cache persistence, domain sets, DoH server groups, TCP speed checks, and `fastest-ip` responses. The repository keeps validation, rendering, and documentation rather than owning a new DNS protocol server.
2. **Build a Python DNS server.** This would add DNS wire-format handling, UDP/TCP listeners, cache expiry, DoH transport, retry logic, and IP-probe scheduling to this project. It is much larger and duplicates an established engine.
3. **Keep the Mihomo-only merge.** This remains useful for routing and first-successful TCP connections, but it does not measure every DNS answer and return the fastest IP.

## Interface

`net-auto-switch dns render --engine smartdns [--config PATH] [--output PATH]` reads the existing `[dns]` upstream and video-domain fields. The current `dns render` behavior remains the Mihomo default. A new `[smartdns]` table supplies `listen` (IPv4 address and port, default `127.0.0.1:6053`), `domestic_domain_set` (required absolute POSIX path to a one-domain-per-line CN list), `cache_file` (required absolute POSIX path), `cache_size` (default 32768), `bootstrap_servers` (IPv4 addresses, default `223.5.5.5` and `1.1.1.1`), and `speed_ports` (default 443 and 80). Unknown keys and unsafe line-breaking values fail validation.

## Generated configuration

The file binds UDP and TCP on the selected address, persists a bounded cache, uses `response-mode fastest-ip` and `max-reply-ip-num 1`, and probes returned IPs with `speed-check-mode tcp:443,tcp:80` (or configured ports). Bootstrap IP servers are excluded from ordinary queries. Global DoH upstreams form the default group. Domestic upstreams form a separate group excluded from the default. The CN domain set and each explicit video domain select the domestic group.

The user supplies the CN domain-set file on the SmartDNS host. Rendering validates its path syntax but does not require the file to exist on the developer's machine. The renderer does not claim that the fastest TCP handshake always means the fastest application transfer; it measures reachability/connection delay on the selected ports. DNS selection does not alter proxy routing.

## Verification

Unit tests parse the generated directives and verify grouping, domain rules, caching, speed mode, CLI output, and rejection of malformed config. Existing Mihomo rendering tests remain green. Documentation shows a complete example and explains that users must install SmartDNS, provide the CN domain list and writable cache directory, and point a DNS client to the generated listener. No live DNS configuration is changed during development.
