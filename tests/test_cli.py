from unittest import mock

import pytest

from net_auto_switch import cli, whois


def _make_install(tmp_path, *, git=False, like_install=True):
    (tmp_path / "config.toml").write_text("secret")
    (tmp_path / ".venv").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "tests").mkdir()  # stale dev dir from a bloated install
    (tmp_path / "SECURITY.md").write_text("x")  # stale dev file
    if like_install:
        (tmp_path / "pyproject.toml").write_text("x")
        (tmp_path / "net_auto_switch").mkdir()
    if git:
        (tmp_path / ".git").mkdir()
    return tmp_path


def test_prune_removes_stale_preserves_runtime(tmp_path):
    d = _make_install(tmp_path)
    cli._prune_for_clean_extract(str(d))
    # runtime state preserved
    assert (d / "config.toml").exists()
    assert (d / ".venv").is_dir()
    assert (d / "logs").is_dir()
    # stale dev files gone
    assert not (d / "tests").exists()
    assert not (d / "SECURITY.md").exists()
    # the package dir itself is replaced by the extract, so it's pruned too
    assert not (d / "net_auto_switch").exists()


def test_prune_skips_dev_checkout(tmp_path):
    d = _make_install(tmp_path, git=True)
    cli._prune_for_clean_extract(str(d))
    assert (d / "tests").exists()  # untouched — has .git
    assert (d / "SECURITY.md").exists()


def test_prune_skips_non_install_dir(tmp_path):
    d = _make_install(tmp_path, like_install=False)
    cli._prune_for_clean_extract(str(d))
    assert (d / "tests").exists()  # untouched — doesn't look like an install


def test_main_once_calls_run_once():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg) as load,
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        inst = Orch.return_value
        cli.main(["--once", "--config", "x.toml"])
    inst.run_once.assert_called_once()
    inst.run_forever.assert_not_called()
    load.assert_called_once_with("x.toml")


def test_main_continuous_calls_run_forever():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg),
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        inst = Orch.return_value
        cli.main([])
    inst.run_forever.assert_called_once()


def test_main_dry_run_passed_through():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg),
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        cli.main(["--once", "--dry-run"])
    _, kwargs = Orch.call_args
    assert kwargs.get("dry_run") is True


def test_main_config_error_exits_nonzero():
    from net_auto_switch.config import ConfigError

    with (
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "load_config", side_effect=ConfigError("no config")),
        mock.patch.object(cli, "log") as log,
        mock.patch.object(cli, "Orchestrator") as Orch,
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--once"])
    assert exc.value.code == 1
    Orch.assert_not_called()
    log.error.assert_called_once()


def test_main_logs_startup_context():
    fake_cfg = mock.Mock()
    with (
        mock.patch.object(cli, "load_config", return_value=fake_cfg),
        mock.patch.object(cli, "_setup_logging"),
        mock.patch.object(cli, "log") as log,
        mock.patch.object(cli, "Orchestrator"),
    ):
        cli.main(["--once", "--dry-run"])
    messages = [c.args[0] for c in log.info.call_args_list if c.args]
    assert any("Starting net-auto-switch" in m for m in messages)
    assert any("dry_run=True" in m for m in messages)


def test_main_init_dispatches_to_cmd_init():
    with mock.patch.object(cli, "cmd_init", return_value=0) as ci:
        with pytest.raises(SystemExit) as exc:
            cli.main(["init", "--yes"])
    assert exc.value.code == 0
    ci.assert_called_once_with(["--yes"])


def test_cmd_init_writes_valid_config(tmp_path, monkeypatch):
    from net_auto_switch.setup import DetectedClash

    det = DetectedClash(
        api="http://127.0.0.1:9097",
        secret="abc",
        proxy_port=7890,
        profiles_yaml=str(tmp_path / "profiles.yaml"),
    )
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: det)
    monkeypatch.setattr(cli, "probe_api", lambda api, secret: "1.0")
    monkeypatch.setattr(cli, "health_check", lambda api, secret: (5, 10))
    monkeypatch.setattr(cli, "read_subscriptions", lambda p: [])
    monkeypatch.setattr(cli, "ClashController", mock.Mock())  # node preview is best-effort

    out = tmp_path / "config.toml"
    rc = cli.cmd_init(["--yes", "--no-service", "--config", str(out)])

    assert rc == 0
    cfg = cli.load_config(str(out))
    assert cfg.clash.secret == "abc"
    assert cfg.clash.proxy_port == 7890


def test_cmd_init_missing_verge_returns_nonzero(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: None)
    assert cli.cmd_init(["--yes", "--no-service"]) == 1


def test_cmd_init_non_macos_aborts(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    assert cli.cmd_init(["--yes", "--no-service"]) == 1


def test_cmd_init_region_prompt_reprompts_on_bad_input(tmp_path, monkeypatch):
    from net_auto_switch.setup import DetectedClash

    det = DetectedClash(
        api="http://127.0.0.1:9097", secret="abc", proxy_port=7890, profiles_yaml="p.yaml"
    )
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: det)
    monkeypatch.setattr(cli, "probe_api", lambda a, s: "1.0")
    monkeypatch.setattr(cli, "health_check", lambda a, s: (5, 5))
    monkeypatch.setattr(cli, "read_subscriptions", lambda p: [])
    ctrl = mock.Mock()
    ctrl.get_proxies.return_value = {"JP-1": {"type": "Vmess"}}
    monkeypatch.setattr(cli, "ClashController", lambda cfg: ctrl)
    monkeypatch.setattr(cli, "detect_regions", lambda names: {"JP": 2, "SG": 1})
    monkeypatch.setattr(cli, "detect_cities", lambda names: {})
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)  # force interactive prompts
    answers = iter(["nope", "1"])  # non-numeric first → re-prompt, then index 1 → JP
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    out = tmp_path / "config.toml"
    assert cli.cmd_init(["--no-service", "--config", str(out)]) == 0
    cfg = cli.load_config(str(out))
    assert cfg.clash.priority == ["JP"]


def test_cmd_init_country_then_city_priority(tmp_path, monkeypatch):
    from net_auto_switch.setup import DetectedClash

    det = DetectedClash(
        api="http://127.0.0.1:9097", secret="abc", proxy_port=7890, profiles_yaml="p.yaml"
    )
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: det)
    monkeypatch.setattr(cli, "probe_api", lambda a, s: "1.0")
    monkeypatch.setattr(cli, "health_check", lambda a, s: (5, 5))
    monkeypatch.setattr(cli, "read_subscriptions", lambda p: [])
    ctrl = mock.Mock()
    ctrl.get_proxies.return_value = {"JP-1": {"type": "Vmess"}}
    monkeypatch.setattr(cli, "ClashController", lambda cfg: ctrl)
    monkeypatch.setattr(cli, "detect_regions", lambda names: {"JP": 2, "US": 1})
    monkeypatch.setattr(cli, "detect_cities", lambda names: {"JP": {"Tokyo": 1, "Osaka": 1}})
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    # countries "1 2" → JP,US; JP has cities → "1" → Tokyo; US has no cities → skipped
    answers = iter(["1 2", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    out = tmp_path / "config.toml"
    assert cli.cmd_init(["--no-service", "--config", str(out)]) == 0
    cfg = cli.load_config(str(out))
    assert cfg.clash.priority == ["JP", "US"]
    assert cfg.clash.cities == {"JP": ["Tokyo"]}


def test_cmd_init_aborts_when_no_reachable_nodes(tmp_path, monkeypatch):
    from net_auto_switch.setup import DetectedClash

    det = DetectedClash(
        api="http://127.0.0.1:9097", secret="abc", proxy_port=7890, profiles_yaml="p.yaml"
    )
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli, "detect_clash_verge", lambda: det)
    monkeypatch.setattr(cli, "probe_api", lambda api, secret: "1.0")
    monkeypatch.setattr(cli, "health_check", lambda api, secret: (0, 8))  # all nodes down
    monkeypatch.setattr(cli, "_confirm", lambda *a, **k: False)  # decline "continue anyway?"

    out = tmp_path / "config.toml"
    assert cli.cmd_init(["--no-service", "--config", str(out)]) == 1
    assert not out.exists()  # aborted before writing


def test_main_update_dispatches_to_cmd_update():
    with mock.patch.object(cli, "cmd_update", return_value=0) as cu:
        with pytest.raises(SystemExit) as exc:
            cli.main(["update"])
    assert exc.value.code == 0
    cu.assert_called_once_with([])


def test_tag_from_release_url():
    assert cli._tag_from_release_url("https://github.com/o/r/releases/tag/v0.3.3") == "v0.3.3"
    assert cli._tag_from_release_url("https://github.com/o/r/releases/tag/v1.2.0/") == "v1.2.0"


def test_version_tuple_and_is_newer():
    assert cli._version_tuple("v0.3.10") == (0, 3, 10)
    assert cli._is_newer("v0.3.10", "0.3.9") is True
    assert cli._is_newer("v0.3.3", "0.3.3") is False
    assert cli._is_newer("v0.2.0", "0.3.0") is False


def test_cmd_update_already_current_skips_download(monkeypatch):
    monkeypatch.setattr(cli, "_resolve_latest_tag", lambda: "v0.3.3")
    monkeypatch.setattr(cli, "_installed_version", lambda: "0.3.3")
    dl = mock.Mock()
    monkeypatch.setattr(cli, "_download_release", dl)
    assert cli.cmd_update([]) == 0
    dl.assert_not_called()


def test_cmd_update_downloads_when_outdated_and_reloads_service(monkeypatch):
    monkeypatch.setattr(cli, "_resolve_latest_tag", lambda: "v0.4.0")
    monkeypatch.setattr(cli, "_installed_version", lambda: "0.3.3")
    monkeypatch.setattr(cli, "_download_release", lambda tag, dest: True)
    monkeypatch.setattr(cli.os.path, "exists", lambda p: True)  # launchd plist present
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or mock.Mock(returncode=0)
    )
    assert cli.cmd_update([]) == 0
    assert ["bash", cli.INSTALL_LAUNCHD] in calls  # reloaded via launchd installer


def test_cmd_update_download_failure_returns_nonzero(monkeypatch):
    monkeypatch.setattr(cli, "_resolve_latest_tag", lambda: "v0.4.0")
    monkeypatch.setattr(cli, "_installed_version", lambda: "0.3.3")
    monkeypatch.setattr(cli, "_download_release", lambda tag, dest: False)
    assert cli.cmd_update([]) == 1


def test_cmd_update_unresolvable_latest_returns_nonzero(monkeypatch):
    monkeypatch.setattr(cli, "_resolve_latest_tag", lambda: None)
    assert cli.cmd_update([]) == 1


def test_cmd_whois_targets_keep_standalone_lookup(monkeypatch):
    calls = []

    def fake_analyze(target, server, authoritative, use_doh):
        calls.append((target, server, authoritative, use_doh))

    monkeypatch.setattr(cli, "load_config", mock.Mock(side_effect=AssertionError))
    monkeypatch.setattr(whois, "analyze", fake_analyze)

    assert cli.cmd_whois(["example.com", "--no-doh"]) == 0

    assert calls == [("example.com", "1.1.1.1", False, False)]


def test_cmd_whois_without_targets_queries_clash_api_nodes(tmp_path, monkeypatch, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profiles_yaml = tmp_path / "profiles.yaml"
    profiles_yaml.write_text(
        """
current: current-uid
items:
  - uid: current-uid
    type: local
    name: Current Profile
    file: current-uid.yaml
  - uid: other-uid
    type: remote
    name: Other Profile
    file: other-uid.yaml
""",
        encoding="utf-8",
    )
    (profiles_dir / "current-uid.yaml").write_text(
        """
proxies:
  - name: Node A
    type: vmess
    server: a.example.com
  - name: Node B
    type: trojan
    server: a.example.com
  - name: Node C
    type: ss
    server: 203.0.113.10
  - name: Profile Only Node
    type: ss
    server: profile-only.example.com
  - name: Broken Node
    type: ss
""",
        encoding="utf-8",
    )

    config = tmp_path / "config.toml"
    # Escape backslashes so a Windows tmp path (C:\...) is a valid TOML string
    # (a bare "\U..." is read as a unicode escape). Round-trips to str(profiles_yaml).
    profiles_yaml_toml = str(profiles_yaml).replace("\\", "\\\\")
    config.write_text(
        f"""
[clash]
secret = "abc"
profiles_yaml = "{profiles_yaml_toml}"
""",
        encoding="utf-8",
    )

    calls = []
    controller_cfgs = []

    class FakeClashController:
        def __init__(self, cfg):
            controller_cfgs.append(cfg)

        def get_proxies(self):
            return {
                "Proxy": {"type": "Selector", "all": ["Node A", "Node B", "Node C"]},
                "Node A": {"type": "Vmess"},
                "Node B": {"type": "Trojan"},
                "Node C": {"type": "Shadowsocks"},
                "DIRECT": {"type": "Direct"},
            }

    def fake_lookup(target, server, authoritative, use_doh):
        calls.append((target, server, authoritative, use_doh))
        return [
            whois.LookupResult(
                target=target,
                ip="198.51.100.7" if target == "a.example.com" else target,
                operator="Cloudflare",
                country="US",
            )
        ]

    monkeypatch.setattr(cli, "ClashController", FakeClashController)
    monkeypatch.setattr(whois, "lookup", fake_lookup)

    assert cli.cmd_whois(["--config", str(config)]) == 0

    assert controller_cfgs
    assert controller_cfgs[0].api == "http://127.0.0.1:9097"
    assert controller_cfgs[0].profiles_yaml == str(profiles_yaml)
    # Lookups run concurrently, so call order is not deterministic.
    assert set(calls) == {
        ("a.example.com", "1.1.1.1", False, True),
        ("203.0.113.10", "1.1.1.1", False, True),
    }
    captured = capsys.readouterr()
    out = captured.out
    # Per-server progress goes to stderr so it doesn't pollute the piped table.
    assert "[1/2]" in captured.err
    assert "[2/2]" in captured.err
    assert "a.example.com" in captured.err
    assert "待解析 server 数 (去重后): 2" in out
    assert "=== [Current Profile] uid=current-uid  节点数: 3 <- current ===" in out
    assert "Node A" in out
    assert "Node B" in out
    assert "Node C" in out
    assert "Profile Only Node" not in out
    assert "a.example.com" in out
    assert "203.0.113.10" in out
    assert "198.51.100.7" in out
    assert "Cloudflare (US)" in out


def test_cmd_whois_without_config_falls_back_to_detected_clash_verge(tmp_path, monkeypatch, capsys):
    from net_auto_switch.config import ConfigError
    from net_auto_switch.setup import DetectedClash

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profiles_yaml = tmp_path / "profiles.yaml"
    profiles_yaml.write_text(
        """
current: current-uid
items:
  - uid: current-uid
    type: remote
    name: Current Profile
    file: current-uid.yaml
""",
        encoding="utf-8",
    )
    (profiles_dir / "current-uid.yaml").write_text(
        """
proxies:
  - name: Node A
    type: vmess
    server: a.example.com
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "load_config", mock.Mock(side_effect=ConfigError("no config")))
    monkeypatch.setattr(
        cli,
        "detect_clash_verge",
        lambda: DetectedClash(
            api="http://127.0.0.1:9097",
            secret="",
            proxy_port=7890,
            profiles_yaml=str(profiles_yaml),
        ),
    )
    monkeypatch.setattr(
        cli,
        "ClashController",
        lambda cfg: mock.Mock(
            get_proxies=lambda: {
                "Proxy": {"type": "Selector", "all": ["Node A"]},
                "Node A": {"type": "Vmess"},
            }
        ),
    )
    monkeypatch.setattr(
        whois,
        "lookup",
        lambda target, server, authoritative, use_doh: [
            whois.LookupResult(
                target=target,
                ip="198.51.100.7",
                operator="Cloudflare",
                country="US",
            )
        ],
    )

    assert cli.cmd_whois([]) == 0

    out = capsys.readouterr().out
    assert "待解析 server 数 (去重后): 1" in out
    assert "Node A" in out
    assert "a.example.com" in out
    assert "Cloudflare (US)" in out


def test_setup_logging_uses_daily_rotation(tmp_path, monkeypatch):
    import logging
    import logging.handlers

    root = logging.getLogger()
    saved = root.handlers[:]
    logpath = tmp_path / "logs" / "nas.log"
    monkeypatch.setattr(cli, "LOG_PATH", str(logpath))
    try:
        cli._setup_logging()
        rotating = [
            h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert rotating, "expected a TimedRotatingFileHandler on the root logger"
        assert rotating[0].backupCount == cli.LOG_BACKUP_DAYS
        assert rotating[0].when == "MIDNIGHT"
        assert logpath.parent.is_dir()
    finally:
        for h in root.handlers:
            if isinstance(h, logging.handlers.TimedRotatingFileHandler):
                h.close()
        root.handlers[:] = saved


def _connections_config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[clash]
secret = "abc"
api = "http://127.0.0.1:9097"
""",
        encoding="utf-8",
    )
    return config


def test_cmd_connections_lists_host_to_node(tmp_path, monkeypatch, capsys):
    config = _connections_config(tmp_path)

    class FakeClashController:
        def __init__(self, cfg):
            pass

        def get_connections(self):
            return [
                {
                    "metadata": {
                        "host": "github.com",
                        "destinationIP": "140.82.112.3",
                        "destinationPort": "443",
                        "network": "tcp",
                    },
                    "chains": ["US-1", "Proxy"],
                    "rule": "DomainSuffix",
                    "rulePayload": "github.com",
                }
            ]

    monkeypatch.setattr(cli, "ClashController", FakeClashController)

    assert cli.cmd_connections(["--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "活动连接: 1" in out
    assert "github.com" in out
    assert "US-1" in out
    assert "DomainSuffix(github.com)" in out


def _dup_controller(n):
    class FakeClashController:
        def __init__(self, cfg):
            pass

        def get_connections(self):
            return [
                {
                    "metadata": {"host": "api.telegram.org", "destinationIP": ""},
                    "chains": ["JP-1"],
                    "rule": "DomainSuffix",
                    "rulePayload": "telegram.org",
                }
                for _ in range(n)
            ]

    return FakeClashController


def test_cmd_connections_aggregates_duplicates_by_default(tmp_path, monkeypatch, capsys):
    config = _connections_config(tmp_path)
    monkeypatch.setattr(cli, "ClashController", _dup_controller(5))

    assert cli.cmd_connections(["--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "活动连接: 5 → 1 组 (host+node)" in out
    assert "CONNS" in out
    assert out.count("api.telegram.org") == 1  # folded into one row
    # the count cell shows 5
    row = next(line for line in out.splitlines() if "api.telegram.org" in line)
    assert "5" in row


def test_cmd_connections_raw_lists_each(tmp_path, monkeypatch, capsys):
    config = _connections_config(tmp_path)
    monkeypatch.setattr(cli, "ClashController", _dup_controller(3))

    assert cli.cmd_connections(["--config", str(config), "--raw"]) == 0
    out = capsys.readouterr().out
    assert "CONNS" not in out
    assert out.count("api.telegram.org") == 3  # one line per connection


def test_enrich_targets_does_not_cache_failures(monkeypatch):
    # A transient empty/failed lookup must stay uncached so a later tick retries it,
    # rather than pinning a permanent blank for the whole watch session.
    n = {"calls": 0}

    def flaky_lookup(target, server, authoritative, use_doh):
        n["calls"] += 1
        if n["calls"] == 1:
            return []  # first attempt fails (e.g. DoH blip)
        return [whois.LookupResult(target=target, ip="1.2.3.4", operator="ACME", country="US")]

    monkeypatch.setattr(whois, "lookup", flaky_lookup)
    cache = {}
    cli._enrich_targets({"a.com"}, cache)
    assert "a.com" not in cache  # failure not cached
    cli._enrich_targets({"a.com"}, cache)  # retried on the next tick
    assert cache["a.com"] == ("1.2.3.4", "ACME (US)")


def test_cmd_connections_empty(tmp_path, monkeypatch, capsys):
    config = _connections_config(tmp_path)

    class FakeClashController:
        def __init__(self, cfg):
            pass

        def get_connections(self):
            return []

    monkeypatch.setattr(cli, "ClashController", FakeClashController)

    assert cli.cmd_connections(["--config", str(config)]) == 0
    assert "活动连接: 0" in capsys.readouterr().out


def test_cmd_connections_whois_enriches_operator(tmp_path, monkeypatch, capsys):
    config = _connections_config(tmp_path)

    class FakeClashController:
        def __init__(self, cfg):
            pass

        def get_connections(self):
            return [
                {
                    "metadata": {
                        "host": "github.com",
                        "destinationIP": "140.82.112.3",
                        "destinationPort": "443",
                    },
                    "chains": ["US-1"],
                }
            ]

    def fake_lookup(target, server, authoritative, use_doh):
        return [
            whois.LookupResult(target=target, ip=target, operator="Microsoft Azure", country="US")
        ]

    monkeypatch.setattr(cli, "ClashController", FakeClashController)
    monkeypatch.setattr(whois, "lookup", fake_lookup)

    assert cli.cmd_connections(["--config", str(config), "--whois"]) == 0
    out = capsys.readouterr().out
    assert "OPERATOR" in out
    assert "140.82.112.3" in out  # destination IP surfaced in its own column
    assert "Microsoft Azure (US)" in out


def test_cmd_connections_whois_resolves_proxied_domain(tmp_path, monkeypatch, capsys):
    # Proxied connections come back from Clash with no destination IP — the
    # operator must be resolved from the host domain instead.
    config = _connections_config(tmp_path)

    class FakeClashController:
        def __init__(self, cfg):
            pass

        def get_connections(self):
            return [
                {
                    "metadata": {"host": "api.anthropic.com", "destinationIP": ""},
                    "chains": ["JP-1"],
                }
            ]

    seen = {}

    def fake_lookup(target, server, authoritative, use_doh):
        seen["target"] = target
        return [
            whois.LookupResult(
                target=target, ip="160.79.104.10", operator="Cloudflare", country="US"
            )
        ]

    monkeypatch.setattr(cli, "ClashController", FakeClashController)
    monkeypatch.setattr(whois, "lookup", fake_lookup)

    assert cli.cmd_connections(["--config", str(config), "--whois"]) == 0
    out = capsys.readouterr().out
    assert seen["target"] == "api.anthropic.com"  # resolved by domain, not by IP
    assert "160.79.104.10" in out  # the resolved IP is shown
    assert "Cloudflare (US)" in out


def test_format_nodes_columns():
    from net_auto_switch.cli import _format_nodes

    rows = [{"name": "JP-1", "region": "JP/Tokyo", "entry": "AWS (JP)"}]
    out = "\n".join(_format_nodes("=== t ===", rows, with_exit=False))
    assert "REGION" in out and "ENTRY" in out and "EXIT" not in out
    assert "JP/Tokyo" in out

    rows2 = [{"name": "JP-1", "region": "JP/Tokyo", "entry": "AWS (JP)", "exit": "GCP (US)"}]
    out2 = "\n".join(_format_nodes("=== t ===", rows2, with_exit=True))
    assert "EXIT" in out2 and "GCP (US)" in out2


def test_node_note_relay_and_name_match():
    from net_auto_switch.cli import _node_note

    assert _node_note("AE", "NL", "AE", with_exit=True) == "中转 NL→AE 名实相符"
    assert "名实不符" in _node_note("US", "NL", "AE", with_exit=True)
    assert _node_note("JP", "JP", "JP", with_exit=True) == "名实相符"


def test_node_note_entry_only():
    from net_auto_switch.cli import _node_note

    assert "入口" in _node_note("AE", "NL", "", with_exit=False)
    assert _node_note("JP", "JP", "", with_exit=False) == ""


def test_enrich_targets_prints_progress(monkeypatch, capsys):
    from net_auto_switch import cli, whois

    class _F:
        def __init__(self, res):
            self._res = res

        def result(self):
            return self._res

    def fake_concurrent(items, *a, **k):
        for t in items:
            yield t, _F([whois.LookupResult(target=t, ip="1.1.1.1", operator="AWS", country="US")])

    monkeypatch.setattr(cli, "_whois_concurrent", fake_concurrent)
    cache = cli._enrich_targets(["a.com", "b.com"], {}, progress=True)
    err = capsys.readouterr().err
    assert "[1/2]" in err and "[2/2]" in err  # per-target progress to stderr
    assert cache["a.com"][1].startswith("AWS")


def test_enrich_targets_silent_without_progress(monkeypatch, capsys):
    from net_auto_switch import cli, whois

    class _F:
        def result(self):
            return [whois.LookupResult(target="x", ip="1.1.1.1", operator="AWS", country="US")]

    monkeypatch.setattr(cli, "_whois_concurrent", lambda items, *a, **k: ((t, _F()) for t in items))
    cli._enrich_targets(["a.com"], {})  # progress defaults False
    assert capsys.readouterr().err == ""


def test_cmd_blacklist_list_and_clear(tmp_path, monkeypatch, capsys):
    from net_auto_switch import blacklist as bl
    from net_auto_switch import cli
    from net_auto_switch.config import ClashConfig

    bl.record_learned(str(tmp_path / "blacklist.json"), "JP-bad", now=1e9)
    monkeypatch.setattr(
        cli, "_resolve_whois_clash_config", lambda c: ClashConfig(state_dir=str(tmp_path))
    )
    assert cli.cmd_blacklist(["list"]) == 0
    assert "JP-bad" in capsys.readouterr().out
    assert cli.cmd_blacklist(["clear"]) == 0
    assert not (tmp_path / "blacklist.json").exists()
