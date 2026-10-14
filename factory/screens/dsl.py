"""The causal factor DSL — how an LLM stage (or a human) declares a
cross-sectional ranking factor the screen can run.

A factor is one expression over the price panels, composed from a closed
set of primitives. Causality is enforced BY CONSTRUCTION, not by review:
every primitive maps the value at date t to a function of rows <= t
(trailing windows, positive lags, per-date cross-sectional transforms),
so the §20.10 rule — every feature reconstructible from data <= t, no
revision of past values — holds for anything the grammar accepts. The
validator is an AST whitelist: no attributes, no subscripts, no names
outside the registry, window/lag arguments must be positive int literals.
A negative shift is not "forbidden" here the way S4's regex forbids it in
strategy source — it is unwritable.

H3's factor, for scale:  ts_ret(close, 40) / ts_std(ts_ret(close, 1), 40)
"""

from __future__ import annotations

import ast

PANELS = ("close", "volume")
# second argument: trailing window / lag length, int literal in [1, MAX_WINDOW]
WINDOW_FUNCS = ("ts_ret", "ts_mean", "ts_std", "ts_min", "ts_max",
                "ts_sum", "ts_lag")
UNARY_FUNCS = ("cs_rank", "cs_zscore", "log", "abs", "sign")
MAX_WINDOW = 365
MAX_EXPR_LEN = 400
_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)


class FactorExprError(ValueError):
    pass


def validate(expr: str) -> ast.Expression:
    """Parse and whitelist-check; raises FactorExprError with the reason."""
    if not isinstance(expr, str) or not expr.strip():
        raise FactorExprError("empty factor expression")
    if len(expr) > MAX_EXPR_LEN:
        raise FactorExprError(f"expression longer than {MAX_EXPR_LEN} chars")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise FactorExprError(f"does not parse: {e}") from None

    uses_panel = False

    def check(node: ast.AST) -> None:
        nonlocal uses_panel
        if isinstance(node, ast.Expression):
            check(node.body)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, _BINOPS):
            check(node.left)
            check(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            check(node.operand)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise FactorExprError(f"literal {node.value!r} is not a number")
        elif isinstance(node, ast.Name):
            if node.id not in PANELS:
                raise FactorExprError(
                    f"name {node.id!r} is not a panel {PANELS}")
            uses_panel = True
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FactorExprError("only plain calls to registry functions")
            fn = node.func.id
            if node.keywords:
                raise FactorExprError(f"{fn}: keyword arguments not allowed")
            if fn in WINDOW_FUNCS:
                if len(node.args) != 2:
                    raise FactorExprError(f"{fn} takes (series, window)")
                check(node.args[0])
                w = node.args[1]
                if (not isinstance(w, ast.Constant)
                        or isinstance(w.value, bool)
                        or not isinstance(w.value, int)
                        or not 1 <= w.value <= MAX_WINDOW):
                    raise FactorExprError(
                        f"{fn}: window must be an int literal in "
                        f"[1, {MAX_WINDOW}] — causality lives here")
            elif fn in UNARY_FUNCS:
                if len(node.args) != 1:
                    raise FactorExprError(f"{fn} takes one argument")
                check(node.args[0])
            else:
                raise FactorExprError(
                    f"unknown function {fn!r}; allowed: "
                    f"{WINDOW_FUNCS + UNARY_FUNCS}")
        else:
            raise FactorExprError(
                f"{type(node).__name__} is not part of the factor grammar")

    check(tree)
    if not uses_panel:
        raise FactorExprError("expression references no price panel")
    return tree


def evaluate(expr: str, panels: dict):
    """Validated evaluation -> wide DataFrame (date x asset), inf -> NaN."""
    import numpy as np
    import pandas as pd  # noqa: F401  (heavy import kept local)

    tree = validate(expr)
    ns = {
        "close": panels["close"],
        "volume": panels.get("volume"),
        "ts_ret": lambda x, n: x.pct_change(n),
        "ts_mean": lambda x, n: x.rolling(n).mean(),
        "ts_std": lambda x, n: x.rolling(n).std(),
        "ts_min": lambda x, n: x.rolling(n).min(),
        "ts_max": lambda x, n: x.rolling(n).max(),
        "ts_sum": lambda x, n: x.rolling(n).sum(),
        "ts_lag": lambda x, n: x.shift(n),
        "cs_rank": lambda x: x.rank(axis=1, pct=True),
        "cs_zscore": lambda x: (x.sub(x.mean(axis=1), axis=0)
                                .div(x.std(axis=1), axis=0)),
        "log": np.log,
        "abs": np.abs,
        "sign": np.sign,
    }
    out = eval(compile(ast.fix_missing_locations(tree), "<factor>", "eval"),
               {"__builtins__": {}}, ns)
    return out.replace([np.inf, -np.inf], np.nan)
