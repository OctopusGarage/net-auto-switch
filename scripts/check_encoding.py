#!/usr/bin/env python3
"""Fail if any `.write_text(...)` / `.read_text(...)` call lacks an explicit
`encoding=`.

ruff's PLW1514 catches `open()` (and builtins) without an encoding, but NOT
pathlib's `Path.write_text` / `Path.read_text`. Those default to the platform
locale — cp1252 on Windows — which silently breaks on our CJK fixtures and only
surfaces in the windows-latest CI job. This AST check blocks them at the lint
gate instead (multi-line- and string-safe, unlike a grep).

Usage: python scripts/check_encoding.py <file.py> [<file.py> ...]
"""

import ast
import sys

_METHODS = {"write_text", "read_text"}


def violations(path):
    with open(path, encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=path)
        except SyntaxError:
            return []
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _METHODS
            and not any(kw.arg == "encoding" for kw in node.keywords)
        ):
            out.append((node.lineno, node.func.attr))
    return out


def main(argv):
    bad = 0
    for path in argv:
        for lineno, method in violations(path):
            print(f"{path}:{lineno}: {method}() without explicit encoding= (cp1252 on Windows)")
            bad += 1
    if bad:
        print(f'\n{bad} encoding violation(s). Add encoding="utf-8".', file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
