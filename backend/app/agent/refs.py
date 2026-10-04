"""Safe data references between plan steps.

Grammar (no eval, no attribute access on Python objects):

    $<step_id|item>( .<field> | [*] | [<n>] )* ( |unique )?

    "$s1.data[*].customer_id|unique"  -> distinct customer ids from step s1
    "$item.id"                         -> field of the current for_each item
"""
from __future__ import annotations

import re
from typing import Any

_HEAD = re.compile(r"^\$([a-z][a-z0-9_]*)")
_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\*|\d+)\]")


class RefError(ValueError):
    pass


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("$")


def parse_ref(ref: str) -> tuple[str, list[tuple[str, str]], bool]:
    expr, unique = (ref[:-7], True) if ref.endswith("|unique") else (ref, False)
    head = _HEAD.match(expr)
    if not head:
        raise RefError(f"Malformed reference '{ref}'")
    pos, tokens = head.end(), []
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            raise RefError(f"Malformed reference '{ref}' near '{expr[pos:]}'")
        tokens.append(("field", m.group(1)) if m.group(1) else ("index", m.group(2)))
        pos = m.end()
    return head.group(1), tokens, unique


def refs_in(value: Any) -> list[str]:
    if is_ref(value):
        return [value]
    if isinstance(value, dict):
        return [r for v in value.values() for r in refs_in(v)]
    if isinstance(value, list):
        return [r for v in value for r in refs_in(v)]
    return []


def _field(obj: Any, name: str, ref: str) -> Any:
    if not isinstance(obj, dict) or name not in obj:
        raise RefError(f"'{name}' not found while resolving {ref}")
    return obj[name]


def resolve_ref(ref: str, scope: dict[str, Any]) -> Any:
    root, tokens, unique = parse_ref(ref)
    if root not in scope:
        raise RefError(f"Unknown reference root '{root}' in {ref}")
    cur, mapped = scope[root], False
    for kind, tok in tokens:
        if kind == "field":
            cur = [_field(v, tok, ref) for v in cur] if mapped else _field(cur, tok, ref)
        elif tok == "*":
            if mapped:
                cur = [x for v in cur for x in (v if isinstance(v, list) else [v])]
            else:
                if not isinstance(cur, list):
                    raise RefError(f"[*] applied to a non-list in {ref}")
                cur, mapped = list(cur), True
        else:
            idx = int(tok)
            try:
                cur = [v[idx] for v in cur] if mapped else cur[idx]
            except (IndexError, TypeError, KeyError) as exc:
                raise RefError(f"Index {idx} out of range in {ref}") from exc
    if unique:
        if not isinstance(cur, list):
            raise RefError(f"|unique applied to a non-list in {ref}")
        seen: list[Any] = []
        for v in cur:
            if v not in seen:
                seen.append(v)
        cur = seen
    return cur


def resolve(value: Any, scope: dict[str, Any]) -> Any:
    """Resolve references anywhere inside a (nested) argument structure."""
    if is_ref(value):
        return resolve_ref(value, scope)
    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in value]
    return value
