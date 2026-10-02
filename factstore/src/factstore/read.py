"""Running one read against the store's views, safely enough to hand the statement to a model.

Every read runs on its own connection in a READ ONLY transaction that is always rolled back,
so nothing it does outlives it: writes fail, and settings it changes (SET ROLE included) are
undone. The statement is prepared, so Postgres refuses more than one. Advisory locks are the
one session state a rollback keeps, and they are released after every read, so a query can
never hold the writer lock.
"""

from dataclasses import dataclass
from datetime import datetime

import psycopg

from . import values
from .errors import FactstoreError

MAX_ROWS = 1000
TIMEOUT_MS = 10_000


class QueryError(FactstoreError):
    pass


class BeforeFirstTransaction(QueryError):
    """as_of is earlier than anything the store recorded."""


@dataclass(frozen=True)
class QueryResult:
    columns: list
    rows: list
    truncated: bool          # more rows matched than were returned
    as_of: int | None        # the transaction read as of; None for current state


def resolve_as_of(conn: psycopg.Connection, as_of) -> int | None:
    """A transaction ID, or the last transaction committed at or before an ISO 8601 instant."""
    if as_of is None:
        return None
    if isinstance(as_of, bool):
        raise QueryError("as_of is a transaction ID or an instant")
    if isinstance(as_of, int) or (isinstance(as_of, str) and as_of.isdigit()):
        tx = int(as_of)
        if conn.execute("select 1 from public.tx where id = %s", (tx,)).fetchone() is None:
            raise QueryError(f"no transaction {tx}")
        return tx
    if isinstance(as_of, str):
        try:
            when = values.coerce("instant", as_of)
        except values.BadValue as exc:
            raise QueryError(f"as_of: {exc}") from None
    elif isinstance(as_of, datetime):
        when = values.coerce("instant", as_of)
    else:
        raise QueryError("as_of is a transaction ID or an instant")
    row = conn.execute("select max(id) from public.tx where at <= %s", (when,)).fetchone()
    if row[0] is None:
        first = conn.execute("select min(at) from public.tx").fetchone()[0]
        raise BeforeFirstTransaction(
            f"the store has no transaction at or before {as_of}; its first was committed at "
            f"{first.isoformat() if first else 'no time yet'}. as_of reads when facts were recorded, not when "
            "they held in the world.")
    return row[0]


def execute(conn: psycopg.Connection, statement: str, *, as_of=None, max_rows: int = MAX_ROWS,
            timeout_ms: int = TIMEOUT_MS) -> QueryResult:
    """Run one SQL statement over the views and return at most max_rows rows. `conn` must be an
    autocommit connection used for nothing else."""
    statement = statement.strip().rstrip(";").strip()
    if not statement:
        raise QueryError("empty query")
    try:
        conn.execute("begin read only")
        try:
            conn.execute("select set_config('statement_timeout', %s, true)", (str(timeout_ms),))
            conn.execute("select set_config('timezone', 'UTC', true)")
            tx = resolve_as_of(conn, as_of)
            if tx is not None:
                conn.execute("select set_config('factstore.as_of', %s, true)", (str(tx),))
            # The same attribute names resolve to current state, or to the store as of tx.
            conn.execute("select set_config('search_path', %s, true)", ("current" if tx is None else "asof",))
            cur = conn.cursor()
            cur.execute(statement, prepare=True)
            if cur.description is None:
                raise QueryError("a query must return rows: write one SELECT (or WITH ... SELECT)")
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
        finally:
            conn.execute("rollback")
            conn.execute("select pg_advisory_unlock_all()")
    except psycopg.errors.QueryCanceled:
        raise QueryError(f"the query ran longer than {timeout_ms / 1000:g} s and was cancelled") from None
    except psycopg.Error as exc:
        raise QueryError(_message(exc)) from None
    return QueryResult(columns, [list(r) for r in rows[:max_rows]], len(rows) > max_rows, tx)


def _message(exc: psycopg.Error) -> str:
    diag = exc.diag
    parts = [diag.message_primary or str(exc).strip()]
    if diag.message_detail:
        parts.append(diag.message_detail)
    if diag.message_hint:
        parts.append(f"Hint: {diag.message_hint}")
    return "\n".join(parts)
