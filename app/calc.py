"""Calculated (derived) columns for collections.

A collection may define named formulas, e.g. {"total": "=quantity*amount"}.
Every row then exposes an extra field `total` computed from its entity values.
Formulas are restricted to arithmetic over entity fields (+ other calc
columns): numbers, + - * / ( ) and identifiers — no function calls, no
attributes, no names beyond the collection's own fields.
"""
import re

from .importer import ENTITY_FIELDS

_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|([+\-*/()]))")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_formula_tokens(formula: str) -> list[str]:
    """Tokenize a formula body (without leading '='). Raises ValueError on
    any character outside numbers, identifiers and arithmetic operators."""
    expr = formula.strip()
    if expr.startswith("="):
        expr = expr[1:]
    tokens, pos = [], 0
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if m is None:
            if expr[pos:].strip() == "":
                break
            raise ValueError(f"illegal character in formula: {expr[pos]!r}")
        number, ident, op = m.groups()
        tokens.append(ident if ident else (number if number else op))
        pos = m.end()
    return tokens


def validate_formula(formula: str, available: set[str]) -> str | None:
    """Return an error message, or None if the formula is valid."""
    try:
        tokens = parse_formula_tokens(formula)
    except ValueError as exc:
        return str(exc)
    if not tokens:
        return "formula is empty"
    for t in tokens:
        if _IDENT.match(t) and t not in available:
            return f"unknown field in formula: {t!r}"
    return None


def _eval_expr(expr: str) -> float | None:
    try:
        value = eval(expr, {"__builtins__": {}}, {})  # noqa: S307 — token-restricted arithmetic only
    except ZeroDivisionError:
        return None
    except Exception:
        return None
    if isinstance(value, bool):
        return None
    return value


def evaluate_formula(formula: str, values: dict) -> float | None:
    """Evaluate one formula against a row. None inputs propagate to None."""
    try:
        tokens = parse_formula_tokens(formula)
    except ValueError:
        return None
    py_tokens = []
    for t in tokens:
        if _IDENT.match(t):
            v = values.get(t)
            if v is None or isinstance(v, (str, bool)):
                return None
            py_tokens.append(repr(float(v)))
        else:
            py_tokens.append(t)
    return _eval_expr(" ".join(py_tokens))


def evaluate_row(formulas: dict[str, str], row: dict) -> dict[str, float | None]:
    """Compute all derived fields for one row. Calc columns may reference
    entity fields and each other; cycles yield None."""
    out: dict[str, float | None] = {}
    computed = dict(row)

    def compute(name: str, stack: set[str]) -> float | None:
        if name in out:
            return out[name]
        if name in stack:
            return None  # cycle
        stack.add(name)
        value = evaluate_formula(formulas[name], computed)
        stack.discard(name)
        out[name] = value
        computed[name] = value
        return value

    for name in formulas:
        compute(name, set())
    return out


def formula_refs(formula: str) -> set[str]:
    """Identifiers referenced by a formula (best effort; bad tokens ignored)."""
    try:
        tokens = parse_formula_tokens(formula)
    except ValueError:
        return set()
    return {t for t in tokens if _IDENT.match(t)}


def detect_cycles(formulas: dict[str, str]) -> list[list[str]]:
    """Cyclic references among calculated columns, e.g. a = b+1, b = a*2.

    Returns a list of cycles (each a list of column names, closed back to its
    start). Empty list = the formula set is a valid DAG.
    """
    graph = {name: formula_refs(f) & set(formulas) for name, f in formulas.items()}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in graph}
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in graph[node]:
            if color[dep] == GRAY:
                cycles.append(path[path.index(dep):] + [dep])
            elif color[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        color[node] = BLACK

    for name in graph:
        if color[name] == WHITE:
            dfs(name, [])
    return cycles


def available_fields(base: dict[str, str]) -> set[str]:
    """Entity fields + calc column names — everything a formula may reference."""
    return set(ENTITY_FIELDS) | set(base)


def calc_to_json(formulas: dict[str, str]) -> str:
    import json
    return json.dumps(formulas, ensure_ascii=False)


def calc_from_json(s: str | None) -> dict[str, str]:
    import json
    return json.loads(s) if s else {}
