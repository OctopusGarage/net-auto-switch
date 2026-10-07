# Mihomo DNS profile design

## Goal

Add an opt-in command that renders a Mihomo DNS configuration for local caching, domain-specific DoH upstreams, and first-successful TCP connection selection. The command must not change the running Clash Verge configuration or the node-switching loop.

## Current state

`net-auto-switch` uses Cloudflare DoH only for `whois` and node metadata lookups. Its `config.toml` controls WiFi and proxy node selection, not DNS. Clash Verge owns the active Mihomo configuration and may reapply its DNS settings after profile enhancements.

## Approaches considered

1. **Render a Mihomo configuration snippet (chosen).** This uses Mihomo's DNS cache, `nameserver-policy`, and `tcp-concurrent`. It is small, testable, and remains compatible with subscription updates. The user applies the snippet as a Clash Verge Global Extension Merge and verifies the effective configuration there.
2. **Write into Clash Verge's profile or runtime files.** This would be easy to invoke but fragile: Verge can regenerate or override those files, and an incorrect write could interrupt the network.
3. **Run a separate local DNS server.** This allows custom TCP latency ranking per answer but requires a new long-running service, port binding, OS DNS changes, cache management, and resolver bootstrap handling. It is outside this first feature.

## User interface

Add `net-auto-switch dns render [--config PATH] [--output PATH]`. With no `--output`, print YAML to stdout. `--output` writes only the named file. The command reads an optional `[dns]` table in the existing TOML configuration; the regular daemon ignores the table. If `[dns]` is absent, the command reports that DNS rendering is not configured.

The table contains:

- `domestic_upstreams`: nonempty list of user-supplied resolver URLs or IPs. This is where a specific "GoDNS" endpoint belongs if that is what the source quote means. No endpoint is guessed.
- `global_upstreams`: nonempty list of DoH URLs, defaulting to `https://dns.google/dns-query` and `https://cloudflare-dns.com/dns-query`.
- `video_domains`: optional list of explicit domain suffixes sent to the domestic upstreams. A video domain is not assumed domestic merely because it carries video.
- `domestic_geosite`: optional Mihomo geosite name, default `cn`. The generated policy uses `geosite:<name>` and requires Mihomo's geosite data to be available.

The renderer validates all inputs before producing output. It emits `dns.enable: true`, `dns.cache-algorithm: arc`, `dns.nameserver-policy` for the domestic geosite and video domains, `dns.nameserver` with the global upstreams, and top-level `tcp-concurrent: true`. It does not change `enhanced-mode`, TUN, fake-IP, DNS listen address, or routing rules.

For example, with a domestic DoH URL of `https://example.net/dns-query` and `video_domains = ["bilibili.com"]`, the rendered YAML is:

```yaml
tcp-concurrent: true
dns:
  enable: true
  cache-algorithm: arc
  nameserver-policy:
    "geosite:cn":
      - https://example.net/dns-query
    "+.bilibili.com":
      - https://example.net/dns-query
  nameserver:
    - https://dns.google/dns-query
    - https://cloudflare-dns.com/dns-query
```

## Behavior and limits

Mihomo owns cache lifetime and DNS protocol handling. Domain policies select resolvers; they do not necessarily select the final proxy route. `tcp-concurrent` races connections to returned IPs and uses the first successful one. It is not a periodic `tcping` benchmark and cannot guarantee the lowest latency for every application request. Domains sent through a remote proxy may be resolved by that proxy; local DNS choices matter most for direct connections and proxy-node bootstrap.

The merge leaves the existing `dns.default-nameserver` unchanged. If an upstream DoH address uses a hostname, the effective configuration needs a reachable IP bootstrap resolver for that hostname.

The command does not automatically edit Clash Verge's DNS settings. Documentation will show how to apply the rendered YAML as a Global Extension Merge, disable Verge's separate DNS override if it is enabled, inspect the effective configuration, and use Mihomo's `/dns/query` endpoint to check representative domestic, video, and overseas domains. Verge can reapply its own DNS settings after the merge, so the effective configuration check is required before calling the setup complete.

## Error handling and verification

Invalid or missing upstreams, malformed domain suffixes, and an invalid geosite name produce a clear error and no partial output. The `--output` path is written atomically after successful rendering. Tests cover rendering, explicit video domains, input validation, and CLI stdout/file behavior. Existing configuration and daemon tests must continue to pass.
