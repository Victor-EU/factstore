"""Low-level writes shared by the store and admin: the writer lock, the schema,
entity allocation, and applying changes to the log and the tables derived from it.

Callers validate first. Everything here assumes the changes are already legal and
runs inside one database transaction holding the writer lock.
"""

from dataclasses import dataclass

from . import fs, values


@dataclass(frozen=True)
class Attr:
    id: int
    ident: str
    type: str
    cardinality: str
    unique: str
    doc: str
    replaced_by: int | None


class Schema:
    def __init__(self, attrs: list[Attr]):
        self.by_id = {a.id: a for a in attrs}
        self.by_ident = {a.ident: a for a in attrs}

    def fs(self, id_: int) -> Attr:
        return self.by_id[id_]


@dataclass(frozen=True)
class Change:
    """One fact to write: an assertion or a retraction of `v` for (`e`, `a`)."""

    e: int
    a: Attr
    v: object
    assert_: bool


def lock(cur) -> None:
    cur.execute("select pg_advisory_xact_lock(%s)", (fs.WRITER_LOCK,))


def load_schema(cur) -> Schema:
    cur.execute("select id, ident, type, cardinality, uniq, doc, replaced_by from attr")
    return Schema([Attr(*row) for row in cur.fetchall()])


def allocate(cur, n: int) -> list[int]:
    if n == 0:
        return []
    cur.execute("select nextval('entity_seq') from generate_series(1, %s)", (n,))
    return [row[0] for row in cur.fetchall()]


def begin_tx(cur) -> int:
    """Start a transaction entity. The schema's triggers stamp its actor and time."""
    tx = allocate(cur, 1)[0]
    cur.execute("insert into tx (id) values (%s)", (tx,))
    return tx


def write(cur, tx: int, changes: list[Change]) -> None:
    """Append `changes` to the log and apply them to current state and the identity index."""
    with cur.copy("copy fact (e, a, v_string, v_decimal, v_boolean, v_date, v_instant, v_ref, tx, op)"
                  " from stdin") as copy:
        for c in changes:
            copy.write_row((c.e, c.a.id, *_columns(c), tx, c.assert_))

    # Retractions first, so a key freed in this transaction can be claimed in it.
    for c in changes:
        if c.assert_:
            continue
        column = values.COLUMN[c.a.type]
        cur.execute(f"delete from cur where e = %s and a = %s and {column} = %s", (c.e, c.a.id, c.v))
        if c.a.unique == "identity":
            cur.execute("delete from ident where a = %s and key = %s", (c.a.id, values.key(c.a.type, c.v)))

    asserted = [c for c in changes if c.assert_]
    with cur.copy("copy cur (e, a, v_string, v_decimal, v_boolean, v_date, v_instant, v_ref, tx) from stdin") as copy:
        for c in asserted:
            copy.write_row((c.e, c.a.id, *_columns(c), tx))
    identity = [(c.a.id, values.key(c.a.type, c.v), c.e) for c in asserted if c.a.unique == "identity"]
    if identity:
        cur.executemany("insert into ident (a, key, e) values (%s, %s, %s)", identity)


def read_value(row) -> object:
    """The one non-null value among the six typed columns."""
    return next(v for v in row if v is not None)


def _columns(c: Change) -> tuple:
    return tuple(c.v if column == values.COLUMN[c.a.type] else None for column in values.COLUMN.values())
