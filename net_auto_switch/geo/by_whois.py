"""Offline country fallback for nodes whose NAME carries no country.

Resolves the node's server address (domain/IP) to an ISO country via whois.
This is the ENTRY side — for the rare relay node with no country in its name it
may report the relay's country rather than the exit. Accepted as a cheap,
side-effect-free backstop; never used to infer city. Returns a code only if it
is in the catalog's known set, else None."""

from .. import whois


def country_of_server(server, known):
    if not server:
        return None
    try:
        results = whois.lookup(server, server="1.1.1.1", authoritative=False, use_doh=True)
    except Exception:
        return None
    for r in results:
        code = (r.country or "").strip().upper()
        if code in known:
            return code
    return None
