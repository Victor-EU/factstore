"""Candidate B: Datomic-style Datalog, written as an EDN string, compiled to the shared engine."""

import re
from dataclasses import dataclass
from decimal import Decimal

from engine import (Agg, BLANK, Const, Fn, GetElse, Missing, Not, Or, Pat, Pred, Pull, Query, QueryError, Rule,
                    RuleCall, Var, parse_instant)


# ---------------------------------------------------------------- EDN

@dataclass(frozen=True)
class Sym:
    name: str


@dataclass(frozen=True)
class Kw:
    name: str


class Lst(list):
    """An EDN list (...), as opposed to a vector [...]."""


class EdnSet(frozenset):
    pass


TOKEN = re.compile(r"""
    (?P<ws>[\s,]+|;[^\n]*)
  | (?P<str>"(?:\\.|[^"\\])*")
  | (?P<open>\#\{|[\[({])
  | (?P<close>[\])}])
  | (?P<tag>\#[a-zA-Z][\w./-]*)
  | (?P<atom>[^\s,\[\](){}"]+)
""", re.X)


def read(text: str):
    items = read_all(text)
    if len(items) != 1:
        raise QueryError("expected exactly one EDN form")
    return items[0]


def read_all(text: str) -> list:
    tokens = []
    pos = 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise QueryError(f"cannot read EDN at: {text[pos:pos + 20]!r}")
        pos = m.end()
        if m.lastgroup != "ws":
            tokens.append((m.lastgroup, m.group()))
    items, i = [], 0
    while i < len(tokens):
        form, i = _form(tokens, i)
        items.append(form)
    return items


def _form(tokens, i):
    kind, tok = tokens[i]
    if kind == "open":
        close = {"[": "]", "(": ")", "{": "}", "#{": "}"}[tok]
        out, i = [], i + 1
        while True:
            if i >= len(tokens):
                raise QueryError(f"unclosed {tok}")
            if tokens[i] == ("close", close):
                i += 1
                break
            if tokens[i][0] == "close":
                raise QueryError(f"expected {close}, found {tokens[i][1]}")
            form, i = _form(tokens, i)
            out.append(form)
        if tok == "(":
            return Lst(out), i
        if tok == "{":
            if len(out) % 2:
                raise QueryError("a map needs an even number of forms")
            return dict(zip(out[::2], out[1::2])), i
        if tok == "#{":
            return EdnSet(out), i
        return out, i
    if kind == "close":
        raise QueryError(f"unexpected {tok}")
    if kind == "str":
        return _string(tok), i + 1
    if kind == "tag":
        value, j = _form(tokens, i + 1)
        if tok == "#inst":
            return parse_instant(value), j
        if tok == "#date":
            from datetime import date
            return date.fromisoformat(value), j
        raise QueryError(f"unknown tag {tok}")
    return _atom(tok), i + 1


def _string(tok):
    body = tok[1:-1]
    return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def _atom(tok):
    if tok == "nil":
        return None
    if tok == "true":
        return True
    if tok == "false":
        return False
    if tok.startswith(":"):
        return Kw(tok[1:])
    if re.fullmatch(r"[+-]?\d+N?", tok):
        return int(tok.rstrip("N"))
    if re.fullmatch(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?M?", tok):
        return Decimal(tok.rstrip("M"))
    return Sym(tok)


# ---------------------------------------------------------------- query

def term(x):
    if isinstance(x, Sym):
        if x.name == "_":
            return BLANK
        if x.name.startswith("?"):
            return Var(x.name[1:])
        raise QueryError(f"unexpected symbol {x.name} (variables start with ?)")
    if isinstance(x, Kw):
        return Const(x.name)
    if isinstance(x, EdnSet):
        return Const(set(x))
    if isinstance(x, list):
        return Const([term(y).value for y in x])
    return Const(x)


def parse(text: str) -> Query:
    """A query vector, optionally followed by its rules vector."""
    forms = read_all(text)
    if not forms or len(forms) > 2:
        raise QueryError("give the query vector, optionally followed by the rules vector")
    q = parse_form(forms[0])
    if len(forms) == 2:
        q.rules = parse_rules_form(forms[1])
    return q


def parse_form(form) -> Query:
    if isinstance(form, dict):
        form = [y for k, v in form.items() for y in [k, *v]]
    if not isinstance(form, list):
        raise QueryError("a query is a vector: [:find ... :where ...]")
    sections, current = {}, None
    for x in form:
        if isinstance(x, Kw) and x.name in ("find", "in", "where", "with", "keys", "strs", "syms"):
            current = x.name
            sections[current] = []
        elif current is None:
            raise QueryError("a query starts with :find")
        else:
            sections[current].append(x)
    if "find" not in sections:
        raise QueryError("missing :find")
    for name in sections.get("in", []):
        if not (isinstance(name, Sym) and name.name in ("$", "%")):
            raise QueryError(":in takes only $ and %; write values into the query itself")
    find = []
    for x in sections["find"]:
        if isinstance(x, Sym) and x.name in (".", "..."):
            continue
        if isinstance(x, list) and not isinstance(x, Lst):  # [?a ...] collection / tuple find specs
            find += [term(y) for y in x if not (isinstance(y, Sym) and y.name == "...")]
            continue
        if isinstance(x, Lst):
            op = x[0].name if isinstance(x[0], Sym) else None
            if op == "pull":
                spec = x[2] if len(x) == 3 else x[1]
                var = x[1] if len(x) == 3 else None
                if isinstance(var, Sym) and var.name == "$":
                    var, spec = x[2], x[3]
                find.append(Pull(term(var), pull_spec(spec)))
            elif op in ("count", "count-distinct", "sum", "min", "max", "avg", "distinct"):
                find.append(Agg(op, term(x[-1])))
            else:
                raise QueryError(f"unknown find expression ({op} ...)")
        else:
            t = term(x)
            if not isinstance(t, Var):
                raise QueryError(f":find takes variables, not {x!r}")
            find.append(t)
    where = [clause(c) for c in sections.get("where", [])]
    columns = [describe(f) for f in find]
    return Query(find=find, where=where, with_=[term(x) for x in sections.get("with", [])],
                 set_semantics=True, columns=columns)


def describe(f):
    if isinstance(f, Var):
        return "?" + f.name
    if isinstance(f, Agg):
        return f"({f.fn} ?{f.var.name})"
    return f"(pull ?{f.var.name})"


def pull_spec(spec):
    out = []
    for item in spec:
        if isinstance(item, Sym) and item.name == "*":
            out.append("*")
        elif isinstance(item, Kw):
            out.append(item.name)
        elif isinstance(item, dict):
            out.append({k.name: pull_spec(v) for k, v in item.items()})
        else:
            raise QueryError(f"pull pattern takes attributes, * and maps, not {item!r}")
    return out


def clause(c):
    if isinstance(c, Lst):
        head = c[0].name if isinstance(c[0], Sym) else None
        if head == "not":
            return Not([clause(x) for x in c[1:]])
        if head == "not-join":
            return Not([clause(x) for x in c[2:]], join=[term(v) for v in c[1]])
        if head == "or":
            return Or([branch(x) for x in c[1:]])
        if head == "or-join":
            return Or([branch(x) for x in c[2:]], join=[term(v) for v in _flat(c[1])])
        if head == "and":
            raise QueryError("(and ...) only appears inside (or ...)")
        if head is None:
            raise QueryError(f"cannot read clause {c!r}")
        return RuleCall(head, [term(x) for x in c[1:] if not (isinstance(x, Sym) and x.name == "$")])
    if not isinstance(c, list) or not c:
        raise QueryError(f"cannot read clause {c!r}")
    if isinstance(c[0], Sym) and c[0].name.startswith("$"):
        c = c[1:]
    if isinstance(c[0], Lst):  # [(pred ...)] or [(fn ...) ?out]
        expr = c[0]
        fn = expr[0].name if isinstance(expr[0], Sym) else None
        args = [x for x in expr[1:] if not (isinstance(x, Sym) and x.name == "$")]
        if fn == "missing?":
            return Missing(term(args[0]), term(args[1]))
        if fn == "get-else":
            return GetElse(term(args[0]), term(args[1]), term(args[2]), term(c[1]))
        if len(c) == 1:
            return Pred(fn, [term(x) for x in args])
        out = term(c[1])
        if not isinstance(out, Var):
            raise QueryError("a function's result must be bound to a variable")
        return Fn(fn, [term(x) for x in args], out)
    parts = [term(x) for x in c]
    if len(parts) < 2 or len(parts) > 5:
        raise QueryError(f"a data pattern has 2 to 5 parts: {c!r}")
    parts += [BLANK] * (5 - len(parts))
    e, a, v, tx, op = parts
    return Pat(e, a, v, tx, op, src="log" if len(c) == 5 else "cur")


def branch(x):
    if isinstance(x, Lst) and isinstance(x[0], Sym) and x[0].name == "and":
        return [clause(y) for y in x[1:]]
    return [clause(x)]


def _flat(x):
    out = []
    for y in x:
        out += _flat(y) if isinstance(y, list) else [y]
    return out


def parse_rules_form(form) -> list[Rule]:
    if not isinstance(form, list):
        raise QueryError("rules are a vector of rules: [[(name ?a ?b) clause ...] ...]")
    rules = []
    for r in form:
        if not isinstance(r, list) or not r or not isinstance(r[0], Lst):
            raise QueryError(f"a rule is [(name ?args ...) clause ...], not {r!r}")
        head = r[0]
        params = [term(x) for x in _flat(head[1:])]
        rules.append(Rule(head[0].name, params, [clause(x) for x in r[1:]]))
    return rules
