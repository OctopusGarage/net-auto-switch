from net_auto_switch import nodes_src


def test_node_servers_from_profile(monkeypatch):
    from net_auto_switch.config import ClashConfig

    monkeypatch.setattr(
        nodes_src,
        "_load_clash_api_profile",
        lambda cfg: {"name": "p", "uid": "u", "nodes": [{"name": "JP-1", "server": "a.com"}]},
    )
    assert nodes_src.node_servers(ClashConfig()) == {"JP-1": "a.com"}


def test_node_servers_returns_empty_on_error(monkeypatch):
    from net_auto_switch.config import ClashConfig

    def _raise(cfg):
        raise nodes_src.WhoisProfileError("boom")

    monkeypatch.setattr(nodes_src, "_load_clash_api_profile", _raise)
    assert nodes_src.node_servers(ClashConfig()) == {}
