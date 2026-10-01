"""The reference reader: a deliberately naive fold over the log. The test oracle for
current state and as-of reads. Never shipped."""

from collections import defaultdict

VALUE_COLUMNS = "v_string, v_decimal, v_boolean, v_date, v_instant, v_ref"


def state(conn, as_of: int | None = None) -> dict[tuple[int, int], frozenset]:
    """{(entity, attribute): values} after every transaction up to `as_of` (all, if None)."""
    rows = conn.execute(
        f"select e, a, {VALUE_COLUMNS}, op from fact where %(t)s::bigint is null or tx <= %(t)s order by tx",
        {"t": as_of},
    ).fetchall()
    values = defaultdict(set)
    for e, a, *cols, op in rows:
        v = next(c for c in cols if c is not None)
        if op:
            values[(e, a)].add(v)
        else:
            values[(e, a)].discard(v)
    return {k: frozenset(vs) for k, vs in values.items() if vs}


def current_table(conn) -> dict[tuple[int, int], frozenset]:
    """The same shape, read from the current-state table the kernel maintains."""
    values = defaultdict(set)
    for e, a, *cols in conn.execute(f"select e, a, {VALUE_COLUMNS} from cur").fetchall():
        values[(e, a)].add(next(c for c in cols if c is not None))
    return {k: frozenset(vs) for k, vs in values.items()}


def attr_id(conn, ident: str) -> int:
    return conn.execute("select id from attr where ident = %s", (ident,)).fetchone()[0]


def value(conn, e: int, ident: str):
    """The current values of one attribute on one entity, from the reference reader."""
    return state(conn).get((e, attr_id(conn, ident)), frozenset())
