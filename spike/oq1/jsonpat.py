"""Candidate A: a JSON pattern language, compiled to the shared engine.

{"where": {"?po": {"po/number": "?n", "po/supplier": {"supplier/code": "NBBW"}}},
 "select": ["?n"]}
"""

import itertools
import json

from engine import (Agg, Const, Fn, Missing, Not, Pat, Path_, Pred, Query, QueryError, Var)

OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "starts_with", "contains", "missing",
             "value", "tx", "op", "log"}
AGGREGATES = {"count", "count_distinct", "sum", "min", "max", "avg"}
COMPARISONS = {"=": "=", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">=", "in": "in", "not_in": "not_in"}
ARITHMETIC = {"+", "-", "*", "/"}


class Compiler:
    def __init__(self):
        self.fresh = itertools.count(1)
        self.clauses = []

    def var(self, name=None):
        return Var(name[1:] if name else f"_{next(self.fresh)}")

    def value(self, x):
        if isinstance(x, str) and x.startswith("?"):
            if len(x) < 2:
                raise QueryError("a variable needs a name after ?")
            return Var(x[1:])
        if isinstance(x, (dict, list)) and not (isinstance(x, list) and all(not isinstance(y, (dict, list)) for y in x)):
            raise QueryError(f"expected a value or variable, got {json.dumps(x)}")
        return Const(x)

    def entity(self, e: Var, pattern: dict, out: list):
        if not isinstance(pattern, dict):
            raise QueryError(f"an entity pattern is an object of attributes, got {json.dumps(pattern)}")
        for key, spec in pattern.items():
            if key == "id":
                continue
            if key == "not":
                inner = []
                self.entity(e, spec, inner)
                out.append(Not(inner))
                continue
            if "/" not in key:
                raise QueryError(f"{key!r} is not an attribute (attributes are namespace/name)")
            reverse = key.startswith("^")
            attr = key[1:] if reverse else key
            hops = None
            if attr.endswith("*") or attr.endswith("+"):
                hops = 0 if attr.endswith("*") else 1
                attr = attr[:-1]
            self.attribute(e, attr, spec, reverse, hops, out)

    def attribute(self, e, attr, spec, reverse, hops, out):
        a = Const(attr)
        if isinstance(spec, dict) and spec and all(k == "id" or "/" in k or k == "not" for k in spec):
            target = self.var(spec.get("id"))
            self.link(e, a, target, reverse, hops, out)
            self.entity(target, spec, out)
            return
        if isinstance(spec, dict):
            unknown = set(spec) - OPERATORS
            if unknown:
                raise QueryError(f"unknown operator(s) {sorted(unknown)} for {attr}; "
                                 f"use one of {sorted(OPERATORS)} or a nested entity pattern")
            if spec.get("missing"):
                if reverse or hops is not None:
                    raise QueryError("missing applies to a plain attribute")
                out.append(Missing(e, a))
                return
            target = self.term(spec["value"], out) if "value" in spec else self.var()
            if "tx" in spec or "op" in spec or spec.get("log"):
                if reverse or hops is not None:
                    raise QueryError("tx, op and log apply to a plain attribute")
                tx = self.term(spec["tx"], out) if "tx" in spec else Var("_")
                op = self.value(spec["op"]) if "op" in spec else Var("_")
                if isinstance(op, Const):
                    op = Const({"assert": True, "retract": False}.get(op.value, op.value))
                log = bool(spec.get("log"))
                opvar = op
                if log and isinstance(op, Var) and op.name != "_":
                    opvar = self.var()
                    out.append(Pat(e, a, target, tx, opvar, src="log"))
                    out.append(_OpName(opvar, op))
                else:
                    out.append(Pat(e, a, target, tx, op, src="log" if log else "cur"))
            else:
                self.link(e, a, target, reverse, hops, out)
            for op_name, arg in spec.items():
                if op_name in ("eq", "ne", "gt", "gte", "lt", "lte"):
                    out.append(Pred(op_name, [target, self.value(arg)]))
                elif op_name in ("in", "not_in"):
                    if not isinstance(arg, list):
                        raise QueryError(f"{op_name} takes a list")
                    out.append(Pred(op_name, [target, Const(arg)]))
                elif op_name in ("starts_with", "contains"):
                    out.append(Pred(op_name, [target, self.value(arg)]))
            return
        self.link(e, a, self.value(spec), reverse, hops, out)

    def term(self, x, out):
        """A value, a variable, or comparisons on a fresh variable: {"lt": "?tx"}."""
        if isinstance(x, dict):
            unknown = set(x) - {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in"}
            if unknown or not x:
                raise QueryError(f"value and tx take a value, a ?variable or comparisons, not {json.dumps(x)}")
            v = self.var()
            for op_name, arg in x.items():
                out.append(Pred(op_name, [v, Const(arg) if isinstance(arg, list) else self.value(arg)]))
            return v
        return self.value(x)

    @staticmethod
    def link(e, a, target, reverse, hops, out):
        src, dst = (target, e) if reverse else (e, target)
        if hops is None:
            out.append(Pat(src, a, dst))
        else:
            out.append(Path_(src, a, dst, hops))


class _OpName(Fn):
    """Binds the log's op (True/False) to "assert"/"retract"."""

    def __init__(self, raw, out):
        super().__init__("opname", [raw], out)


def parse(text: str) -> Query:
    try:
        q = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QueryError(f"not JSON: {exc}")
    if not isinstance(q, dict):
        raise QueryError("a query is an object with where and select")
    unknown = set(q) - {"where", "select", "filter", "let", "order_by", "limit"}
    if unknown:
        raise QueryError(f"unknown query keys {sorted(unknown)}")
    c = Compiler()
    where = []
    patterns = q.get("where")
    if isinstance(patterns, dict):
        patterns = [{**p, "id": name} if isinstance(p, dict) else p for name, p in patterns.items()]
    if not isinstance(patterns, list):
        raise QueryError("where maps ?variables to entity patterns, or lists patterns that each have an id")
    for pattern in patterns:
        name = pattern.get("id") if isinstance(pattern, dict) else None
        if not (isinstance(name, str) and name.startswith("?")):
            raise QueryError(f"each entity pattern needs a ?variable naming it, got {json.dumps(pattern)}")
        c.entity(Var(name[1:]), pattern, where)
    for name, expr in (q.get("let") or {}).items():
        if not name.startswith("?") or not isinstance(expr, list) or not expr or expr[0] not in ARITHMETIC:
            raise QueryError('let maps a ?variable to ["+"|"-"|"*"|"/", operand, ...]')
        where.append(Fn(expr[0], [c.value(x) for x in expr[1:]], Var(name[1:])))
    for f in q.get("filter") or []:
        if not isinstance(f, list) or len(f) != 3 or f[0] not in COMPARISONS:
            raise QueryError('a filter is [op, a, b] with op one of = != < <= > >= in not_in')
        where.append(Pred(COMPARISONS[f[0]], [c.value(f[1]), Const(f[2]) if isinstance(f[2], list) else c.value(f[2])]))
    find, columns = [], []
    select = q.get("select")
    if not isinstance(select, list) or not select:
        raise QueryError("select is a list of ?variables and aggregates like {\"sum\": \"?x\"}")
    for s in select:
        if isinstance(s, str) and s.startswith("?"):
            find.append(Var(s[1:]))
            columns.append(s)
        elif isinstance(s, dict) and len(s) == 1 and next(iter(s)) in AGGREGATES:
            fn, v = next(iter(s.items()))
            find.append(Agg(fn, c.value(v)))
            columns.append(f"{fn}({v})")
        else:
            raise QueryError(f"cannot select {json.dumps(s)}")
    order = []
    for o in q.get("order_by") or []:
        desc = o.startswith("-")
        order.append((Var(o.lstrip("-")[1:]), desc))
    return Query(find=find, where=where, set_semantics=False, order_by=order, limit=q.get("limit"), columns=columns)
