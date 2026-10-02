"""A naive in-memory query engine shared by candidates A (JSON patterns) and B (Datalog).

Both front ends compile to the clauses below. Evaluation is a nested-loop join over a fold of
the log, with greedy clause ordering. Good enough to score correctness in the spike; whichever
language wins gets a real compiler to SQL in M2.
"""

import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

CACHE = Path(__file__).with_name("cache")


class QueryError(Exception):
    pass


# ---------------------------------------------------------------- terms and clauses

@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Const:
    value: object


BLANK = Var("_")


@dataclass
class Pat:
    """[e a v tx op]. src "cur" reads current state (tx: the transaction that asserted the value);
    "log" reads every fact up to as-of, with op True for assert and False for retract."""
    e: object
    a: object
    v: object = BLANK
    tx: object = BLANK
    op: object = BLANK
    src: str = "cur"


@dataclass
class Pred:
    fn: str
    args: list


@dataclass
class Fn:
    fn: str
    args: list
    out: Var


@dataclass
class Not:
    clauses: list
    join: list | None = None


@dataclass
class Or:
    branches: list  # list of clause lists
    join: list | None = None


@dataclass
class RuleCall:
    name: str
    args: list


@dataclass
class Path_:
    """e reaches v through `a` in min_hops or more steps (0: e itself counts)."""
    e: object
    a: object
    v: object
    min_hops: int = 0


@dataclass
class Missing:
    e: object
    a: object


@dataclass
class GetElse:
    e: object
    a: object
    default: object
    out: Var


@dataclass
class Rule:
    name: str
    params: list
    body: list


@dataclass
class Agg:
    fn: str
    var: Var


@dataclass
class Pull:
    var: Var
    spec: list


@dataclass
class Query:
    find: list            # Var | Agg | Pull
    where: list
    with_: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    set_semantics: bool = True   # Datomic: aggregate over the distinct basis set; else over every match
    order_by: list = field(default_factory=list)  # (Var, descending)
    limit: int | None = None
    columns: list | None = None


def vars_of(term_list) -> set:
    return {t.name for t in term_list if isinstance(t, Var) and t.name != "_"}


def clause_vars(c) -> set:
    if isinstance(c, Pat):
        return vars_of([c.e, c.a, c.v, c.tx, c.op])
    if isinstance(c, Pred):
        return vars_of(c.args)
    if isinstance(c, Fn):
        return vars_of(c.args) | vars_of([c.out])
    if isinstance(c, Not):
        return set().union(*(clause_vars(x) for x in c.clauses)) if c.join is None else vars_of(c.join)
    if isinstance(c, Or):
        if c.join is not None:
            return vars_of(c.join)
        return set().union(*(clause_vars(x) for b in c.branches for x in b))
    if isinstance(c, RuleCall):
        return vars_of(c.args)
    if isinstance(c, Path_):
        return vars_of([c.e, c.a, c.v])
    if isinstance(c, Missing):
        return vars_of([c.e, c.a])
    if isinstance(c, GetElse):
        return vars_of([c.e, c.a, c.out])
    raise QueryError(f"unknown clause {c!r}")


# ---------------------------------------------------------------- the database

class DB:
    def __init__(self, log, attrs, as_of=None):
        """log: (e, a, v, tx, op) in tx order; attrs: id -> (ident, type, cardinality)."""
        self.attrs = attrs
        self.by_ident = {ident: (aid, type_, card) for aid, (ident, type_, card) in attrs.items()}
        self.log_a = defaultdict(list)
        self.log_ea = defaultdict(list)
        last = {}
        for e, a, v, tx, op in log:
            if as_of is not None and tx > as_of:
                break
            self.log_a[a].append((e, v, tx, op))
            self.log_ea[(e, a)].append((v, tx, op))
            last[(e, a, v)] = (tx, op)
        self.cur_a = defaultdict(list)
        self.cur_ea = defaultdict(list)
        self.cur_av = defaultdict(list)
        for (e, a, v), (tx, op) in last.items():
            if op:
                self.cur_a[a].append((e, v, tx))
                self.cur_ea[(e, a)].append((v, tx))
                self.cur_av[(a, v)].append((e, tx))

    def attr(self, ident):
        if isinstance(ident, int) and ident in self.attrs:
            return ident, self.attrs[ident][1]
        if ident not in self.by_ident:
            raise QueryError(f"unknown attribute {ident!r}")
        aid, type_, _ = self.by_ident[ident]
        return aid, type_


def load_db(dsn: str, as_of=None, refresh=False) -> DB:
    import psycopg

    CACHE.mkdir(exist_ok=True)
    path = CACHE / "log.pkl"
    if refresh or not path.exists():
        with psycopg.connect(dsn) as conn:
            attrs = {aid: (ident, type_, card) for aid, ident, type_, card in
                     conn.execute("select id, ident, type, cardinality from attr")}
            rows = conn.execute(
                "select e, a, v_string, v_decimal, v_boolean, v_date, v_instant, v_ref, tx, op from fact"
                " order by tx, e, a").fetchall()
        log = []
        for e, a, s, d, b, dt, inst, ref, tx, op in rows:
            v = next(x for x in (s, d, b, dt, inst, ref) if x is not None)
            if isinstance(v, datetime):
                v = v.astimezone(timezone.utc)
            log.append((e, a, v, tx, op))
        path.write_bytes(pickle.dumps((attrs, log)))
    attrs, log = pickle.loads(path.read_bytes())
    if isinstance(as_of, (datetime, str)):
        as_of = tx_at(attrs, log, as_of)
    return DB(log, attrs, as_of)


def tx_at(attrs, log, when) -> int:
    """The last transaction committed at or before `when`."""
    if isinstance(when, str):
        when = parse_instant(when)
    at_id = next(aid for aid, (ident, _, _) in attrs.items() if ident == "fs/at")
    best = 0
    for e, a, v, tx, op in log:
        if a == at_id and op and v <= when:
            best = max(best, e)
    return best


# ---------------------------------------------------------------- values

def parse_instant(s: str) -> datetime:
    s = s.strip()
    if len(s) == 10:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise QueryError(f"instant without a timezone: {s!r}")
    return dt.astimezone(timezone.utc)


def coerce(type_, value):
    """A query constant as a value of the attribute's type."""
    try:
        if type_ == "string":
            return value if isinstance(value, str) else str(value)
        if type_ == "decimal":
            return value if isinstance(value, Decimal) else Decimal(str(value))
        if type_ == "boolean":
            return value if isinstance(value, bool) else str(value).lower() == "true"
        if type_ == "date":
            if isinstance(value, datetime):
                return value.date()
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if type_ == "instant":
            return value if isinstance(value, datetime) else parse_instant(str(value))
        if type_ == "ref":
            if isinstance(value, bool):
                raise ValueError
            return int(value)
    except (ValueError, InvalidOperation):
        raise QueryError(f"{value!r} is not a {type_}")
    return value


def comparable(a, b):
    """Bring two values to a common type for comparison, the way SQL casts a literal."""
    def conv(x, like):
        if isinstance(like, datetime) and not isinstance(x, datetime):
            if isinstance(x, date):
                return datetime(x.year, x.month, x.day, tzinfo=timezone.utc)
            if isinstance(x, str):
                return parse_instant(x)
        if isinstance(like, date) and not isinstance(like, datetime):
            if isinstance(x, datetime):
                return x.date()
            if isinstance(x, str):
                return date.fromisoformat(x)
        if isinstance(like, Decimal) and isinstance(x, (int, float, str)) and not isinstance(x, bool):
            return Decimal(str(x))
        if isinstance(like, int) and not isinstance(like, bool) and isinstance(x, Decimal):
            return x
        return x
    try:
        a2, b2 = conv(a, b), conv(b, a)
        if isinstance(a2, int) and isinstance(b2, Decimal):
            a2 = Decimal(a2)
        if isinstance(b2, int) and isinstance(a2, Decimal):
            b2 = Decimal(b2)
        return a2, b2
    except ValueError as exc:
        raise QueryError(str(exc))


def compare(fn, a, b):
    if a is None or b is None:
        return False
    a, b = comparable(a, b)
    try:
        if fn in ("=", "==", "eq"):
            return a == b
        if fn in ("!=", "not=", "ne"):
            return a != b
        if fn in ("<", "lt"):
            return a < b
        if fn in ("<=", "lte"):
            return a <= b
        if fn in (">", "gt"):
            return a > b
        if fn in (">=", "gte"):
            return a >= b
    except TypeError:
        raise QueryError(f"cannot compare {a!r} with {b!r}")
    raise QueryError(f"unknown comparison {fn}")


def arith(fn, args):
    vals = []
    for x in args:
        if isinstance(x, bool) or x is None:
            raise QueryError(f"{fn} needs numbers, got {x!r}")
        if isinstance(x, (int, float, str)):
            try:
                x = Decimal(str(x))
            except InvalidOperation:
                raise QueryError(f"{fn} needs numbers, got {x!r}")
        if not isinstance(x, Decimal):
            if fn == "-" and len(args) == 2 and all(isinstance(y, (date, datetime)) for y in args):
                d = args[0] - args[1]
                return Decimal(d.days) if isinstance(args[0], date) and not isinstance(args[0], datetime) \
                    else Decimal(str(d.total_seconds()))
            raise QueryError(f"{fn} needs numbers, got {x!r}")
        vals.append(x)
    if fn == "+":
        return sum(vals, Decimal(0))
    if fn == "*":
        out = Decimal(1)
        for v in vals:
            out *= v
        return out
    if fn == "-":
        return -vals[0] if len(vals) == 1 else vals[0] - sum(vals[1:], Decimal(0))
    if fn == "/":
        out = vals[0]
        for v in vals[1:]:
            if v == 0:
                raise QueryError("division by zero")
            out /= v
        return out
    raise QueryError(f"unknown function {fn}")


# ---------------------------------------------------------------- evaluation

class Engine:
    def __init__(self, db: DB, rules=()):
        self.db = db
        self.rules = defaultdict(list)
        for r in rules:
            self.rules[r.name].append(r)
        self.relations = {}

    # -- resolution of terms against a binding
    @staticmethod
    def val(term, b):
        if isinstance(term, Const):
            return True, term.value
        if term.name == "_":
            return False, None
        if term.name in b:
            return True, b[term.name]
        return False, None

    @staticmethod
    def bind(b, term, value):
        """Extend binding b with term=value; None if inconsistent."""
        if isinstance(term, Const):
            return b if term.value == value else None
        if term.name == "_":
            return b
        if term.name in b:
            return b if b[term.name] == value else None
        nb = dict(b)
        nb[term.name] = value
        return nb

    def solve(self, clauses, bindings):
        pending = list(clauses)
        bound = set(bindings[0]) if bindings else set()
        while pending:
            c = self.pick(pending, bound)
            pending.remove(c)
            out = []
            for b in bindings:
                out.extend(self.step(c, b))
            bindings = out
            bound |= clause_vars(c) if not isinstance(c, Not) else set()
            if not bindings:
                return []
        return bindings

    def pick(self, pending, bound):
        best, best_score = None, None
        for c in pending:
            vs = clause_vars(c)
            if isinstance(c, Not) and c.join is None:
                # Variables only the not-clause mentions are its own; the rest must be bound first.
                later = set().union(*(clause_vars(x) for x in pending if x is not c and not isinstance(x, Not)))
                score = 0 if not ((vs - bound) & later) else None
            elif isinstance(c, (Pred, Not, Missing)):
                score = 0 if vs <= bound else None
            elif isinstance(c, Fn):
                score = 0 if vars_of(c.args) <= bound else None
            elif isinstance(c, GetElse):
                score = 1 if vars_of([c.e]) <= bound else None
            elif isinstance(c, Or):
                score = 2 if (c.join is None or vars_of(c.join) & bound) else 50
            elif isinstance(c, Pat):
                e_b = isinstance(c.e, Const) or (isinstance(c.e, Var) and c.e.name in bound)
                v_b = isinstance(c.v, Const) or (isinstance(c.v, Var) and c.v.name in bound)
                a_b = isinstance(c.a, Const) or (isinstance(c.a, Var) and c.a.name in bound)
                score = 3 if e_b else 4 if v_b else 10 if a_b else 100
                if c.src == "log":
                    score += 1
            elif isinstance(c, (RuleCall, Path_)):
                score = 5 if vs & bound else 20
            else:
                score = 30
            if score is not None and (best_score is None or score < best_score):
                best, best_score = c, score
        if best is None:
            names = sorted(set().union(*(clause_vars(c) for c in pending)) - bound)
            raise QueryError(f"insufficient bindings: nothing binds {', '.join('?' + n for n in names)}")
        return best

    def step(self, c, b):
        if isinstance(c, Pat):
            return self.match(c, b)
        if isinstance(c, Pred):
            return [b] if self.pred(c, b) else []
        if isinstance(c, Fn):
            args = [self.need(t, b) for t in c.args]
            if c.fn in ("+", "-", "*", "/"):
                value = arith(c.fn, args)
            elif c.fn in ("ground", "identity"):
                value = args[0]
            elif c.fn == "opname":
                value = "assert" if args[0] else "retract"
            elif c.fn in ("str", "concat"):
                value = "".join(str(a) for a in args)
            else:
                raise QueryError(f"unknown function {c.fn}")
            nb = self.bind(b, c.out, value)
            return [nb] if nb is not None else []
        if isinstance(c, Not):
            return [] if self.solve(c.clauses, [b]) else [b]
        if isinstance(c, Or):
            out, seen = [], set()
            for branch in c.branches:
                for nb in self.solve(branch, [b]):
                    keep = {k: v for k, v in nb.items() if c.join is None or k in b or k in vars_of(c.join)}
                    key = tuple(sorted(keep.items(), key=lambda kv: kv[0]))
                    if key not in seen:
                        seen.add(key)
                        out.append(keep)
            return out
        if isinstance(c, RuleCall):
            rel = self.relation(c.name, len(c.args))
            out = []
            for row in rel:
                nb = b
                for t, v in zip(c.args, row):
                    nb = self.bind(nb, t, v)
                    if nb is None:
                        break
                if nb is not None:
                    out.append(nb)
            return out
        if isinstance(c, Path_):
            return self.path(c, b)
        if isinstance(c, Missing):
            e = self.need(c.e, b)
            aid, _ = self.db.attr(self.need(c.a, b))
            return [b] if not self.db.cur_ea.get((e, aid)) else []
        if isinstance(c, GetElse):
            e = self.need(c.e, b)
            aid, _ = self.db.attr(self.need(c.a, b))
            vs = self.db.cur_ea.get((e, aid))
            value = vs[0][0] if vs else c.default.value if isinstance(c.default, Const) else self.need(c.default, b)
            nb = self.bind(b, c.out, value)
            return [nb] if nb is not None else []
        raise QueryError(f"unknown clause {c!r}")

    def need(self, term, b):
        ok, v = self.val(term, b)
        if not ok:
            raise QueryError(f"?{term.name} is not bound where it is used")
        return v

    def pred(self, c, b):
        args = [self.need(t, b) for t in c.args]
        fn = c.fn
        if fn in ("<", "<=", ">", ">=", "=", "==", "!=", "not=", "eq", "ne", "lt", "lte", "gt", "gte"):
            if fn in ("<", "<=", ">", ">=") and len(args) > 2:
                return all(compare(fn, x, y) for x, y in zip(args, args[1:]))
            return compare(fn, args[0], args[1])
        if fn in ("contains?", "in"):
            coll, x = (args[0], args[1]) if fn == "contains?" else (args[1], args[0])
            return any(compare("=", x, y) for y in coll)
        if fn == "not_in":
            return not any(compare("=", args[0], y) for y in args[1])
        if fn in ("starts-with?", "starts_with"):
            return isinstance(args[0], str) and args[0].startswith(str(args[1]))
        if fn in ("includes?", "contains"):
            return isinstance(args[0], str) and str(args[1]) in args[0]
        raise QueryError(f"unknown predicate {fn}")

    def match(self, c, b):
        db = self.db
        a_ok, a = self.val(c.a, b)
        if not a_ok:
            out = []
            for aid in db.attrs:
                out.extend(self.match(Pat(c.e, Const(aid), c.v, c.tx, c.op, c.src), self.bind(b, c.a, db.attrs[aid][0])))
            return out
        aid, type_ = db.attr(a)
        e_ok, e = self.val(c.e, b)
        v_ok, v = self.val(c.v, b)
        if v_ok:
            v = coerce(type_, v) if isinstance(c.v, Const) else v
        out = []
        if c.src == "cur":
            if e_ok:
                rows = ((e, vv, tx) for vv, tx in db.cur_ea.get((e, aid), ()))
            elif v_ok:
                rows = ((ee, v, tx) for ee, tx in db.cur_av.get((aid, v), ()))
            else:
                rows = db.cur_a.get(aid, ())
            for ee, vv, tx in rows:
                nb = self.bind(b, c.e, ee)
                if nb is not None:
                    nb = self.bind(nb, c.v, vv)
                if nb is not None:
                    nb = self.bind(nb, c.tx, tx)
                if nb is not None and not (isinstance(c.op, Const) and c.op.value is not True):
                    nb = self.bind(nb, c.op, True)
                    if nb is not None:
                        out.append(nb)
        else:
            rows = ((e, vv, tx, op) for vv, tx, op in db.log_ea.get((e, aid), ())) if e_ok else db.log_a.get(aid, ())
            for ee, vv, tx, op in rows:
                nb = self.bind(b, c.e, ee)
                for t, x in ((c.v, vv), (c.tx, tx), (c.op, op)):
                    if nb is None:
                        break
                    nb = self.bind(nb, t, x)
                if nb is not None:
                    out.append(nb)
        return out

    def relation(self, name, arity):
        key = (name, arity)
        if key in self.relations:
            return self.relations[key]
        rules = [r for r in self.rules.get(name, []) if len(r.params) == arity]
        if not rules:
            raise QueryError(f"unknown rule ({name}) with {arity} arguments")
        self.relations[key] = set()
        while True:
            new = set()
            for r in rules:
                for sol in self.solve(r.body, [{}]):
                    try:
                        new.add(tuple(sol[p.name] if isinstance(p, Var) else p.value for p in r.params))
                    except KeyError as missing:
                        raise QueryError(f"rule ({name}) never binds ?{missing.args[0]}")
            if new <= self.relations[key]:
                return self.relations[key]
            self.relations[key] |= new

    def path(self, c, b):
        aid, _ = self.db.attr(self.need(c.a, b) if isinstance(c.a, Var) else c.a.value)
        reverse = False
        e_ok, e = self.val(c.e, b)
        v_ok, v = self.val(c.v, b)
        if not e_ok and v_ok:
            reverse, start = True, v
        elif e_ok:
            start = e
        else:
            out = []
            for ee, _, _ in self.db.cur_a.get(aid, ()):
                out.extend(self.path(c, self.bind(b, c.e, ee)))
            if c.min_hops == 0:
                pass
            return out
        seen, frontier, reached = {start}, [start], []
        if c.min_hops == 0:
            reached.append(start)
        while frontier:
            nxt = []
            for x in frontier:
                if reverse:
                    ys = [ee for ee, _ in self.db.cur_av.get((aid, x), ())]
                else:
                    ys = [vv for vv, _ in self.db.cur_ea.get((x, aid), ())]
                for y in ys:
                    if y not in seen:
                        seen.add(y)
                        nxt.append(y)
                        reached.append(y)
            frontier = nxt
        out = []
        for r in reached:
            nb = self.bind(b, c.e if reverse else c.v, r)
            if nb is not None:
                out.append(nb)
        return out

    # -- the whole query
    def run(self, q: Query):
        sols = self.solve(q.where, [{}])
        aggs = [f for f in q.find if isinstance(f, Agg)]
        plain = [f for f in q.find if isinstance(f, Var)]
        for f in q.find:
            names = [f.name] if isinstance(f, Var) else [f.var.name]
            for n in names:
                if sols and n not in sols[0] and n != "_":
                    raise QueryError(f"?{n} in find is not bound by the query")
        if not aggs:
            rows, seen = [], set()
            for s in sols:
                row = tuple(self.output(f, s) for f in q.find)
                key = repr(row)
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
        else:
            keyvars = [f.name for f in plain]
            basis_vars = keyvars + [n.name for n in q.with_] + [a.var.name for a in aggs]
            if q.set_semantics:
                uniq = {tuple(s.get(n) for n in basis_vars): s for s in sols}
                sols = list(uniq.values())
            groups = defaultdict(list)
            for s in sols:
                groups[tuple(s[n] for n in keyvars)].append(s)
            if not keyvars and not groups:
                groups[()] = []
            rows = []
            for key, members in groups.items():
                kv = dict(zip(keyvars, key))
                row = []
                for f in q.find:
                    if isinstance(f, Var):
                        row.append(kv[f.name])
                    else:
                        row.append(aggregate(f.fn, [m[f.var.name] for m in members]))
                rows.append(tuple(row))
        for var, desc in reversed(q.order_by):
            idx = next((i for i, f in enumerate(q.find) if isinstance(f, Var) and f.name == var.name), None)
            if idx is None:
                raise QueryError(f"order by ?{var.name}: it must be in the result")
            rows.sort(key=lambda r: (r[idx] is None, r[idx]), reverse=desc)
        if q.limit is not None:
            rows = rows[:q.limit]
        return rows

    def output(self, f, s):
        if isinstance(f, Var):
            return s[f.name]
        if isinstance(f, Pull):
            return self.pull(s[f.var.name], f.spec)
        raise QueryError(f"cannot output {f!r}")

    def pull(self, e, spec):
        out = {"id": e}
        for item in spec:
            if item == "*":
                for (ee, aid), vs in ((k, v) for k, v in self.db.cur_ea.items() if k[0] == e):
                    ident, _, card = self.db.attrs[aid]
                    out[ident] = [v for v, _ in vs] if card == "many" else vs[0][0]
            elif isinstance(item, dict):
                for ident, sub in item.items():
                    aid, _ = self.db.attr(ident)
                    vs = [v for v, _ in self.db.cur_ea.get((e, aid), ())]
                    card = self.db.attrs[aid][2]
                    pulled = [self.pull(v, sub) for v in vs]
                    if pulled:
                        out[ident] = pulled if card == "many" else pulled[0]
            else:
                aid, _ = self.db.attr(item)
                vs = [v for v, _ in self.db.cur_ea.get((e, aid), ())]
                if vs:
                    out[item] = vs if self.db.attrs[aid][2] == "many" else vs[0]
        return out


def aggregate(fn, values):
    fn = fn.replace("-", "_")
    if fn == "count":
        return len(values)
    if fn == "count_distinct":
        return len(set(values))
    values = [v for v in values if v is not None]
    if fn == "distinct":
        return sorted(set(values), key=str)
    if not values:
        return None
    if fn == "sum":
        return arith("+", values)
    if fn == "avg":
        return arith("+", values) / len(values)
    if fn == "min":
        return min(values)
    if fn == "max":
        return max(values)
    raise QueryError(f"unknown aggregate {fn}")


def to_json(v):
    if isinstance(v, bool) or v is None or isinstance(v, int):
        return v
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral() else format(v, "f")
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple, set)):
        return [to_json(x) for x in v]
    if isinstance(v, dict):
        return {k: to_json(x) for k, x in v.items()}
    return v
