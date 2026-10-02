"""The read side's views: one per attribute, in schema current (current state), schema asof (the
state as of factstore.as_of) and schema history (the log). Checked against the reference reader."""

from collections import defaultdict

import psycopg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import reference
from conftest import attr
from factstore import TransactError

ENTITIES = 4
ATTRS = {
    "prop/name": ("string", "one", ["a", "b", "c"], "What a test entity is called."),
    "prop/tags": ("string", "many", ["x", "y", "z"], "Labels stuck on a test entity, any number of them."),
    "prop/amount": ("decimal", "one", ["1", "2.50", "10"], "Money owed on it, exact."),
    "prop/due": ("date", "one", ["2026-01-01", "2026-02-01"], "Calendar day payment falls due."),
    "prop/links": ("ref", "many", [0, 1, 2, 3], "Other test entities this one points at."),
}

ops = st.lists(st.tuples(st.integers(0, ENTITIES - 1), st.sampled_from(sorted(ATTRS)), st.integers(0, 3),
                         st.sampled_from(["assert", "retract"])), min_size=1, max_size=6)


def read_view(conn, schema, as_of=None) -> dict:
    """{(entity, attribute id): values} from every attribute's view, as reference.state shapes it."""
    out = defaultdict(set)
    ids = dict(conn.execute("select ident, id from attr").fetchall())
    with conn.transaction():
        if as_of is not None:
            conn.execute("select set_config('factstore.as_of', %s, true)", (str(as_of),))
        for ident, a in ids.items():
            for e, v in conn.execute(psycopg.sql.SQL("select e, v from {}.{}").format(
                    psycopg.sql.Identifier(schema), psycopg.sql.Identifier(ident))):
                out[(e, a)].add(v)
    return {k: frozenset(vs) for k, vs in out.items()}


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(batches=st.lists(ops, min_size=1, max_size=6))
def test_views_equal_the_reference_reader_now_and_as_of(store, batches):
    store.register_attribute([attr(i, t, c, doc) for i, (t, c, _, doc) in ATTRS.items()])
    seed = store.transact([{"e": f"tmp:{i}", "a": "prop/name", "v": "seed"} for i in range(ENTITIES)])
    ids = [seed.tempids[f"tmp:{i}"] for i in range(ENTITIES)]
    txs = [seed.tx]
    for batch in batches:
        facts = []
        for e, a, k, op in batch:
            values = ATTRS[a][2]
            v = values[k % len(values)]
            facts.append({"e": ids[e], "a": a, "v": ids[v] if ATTRS[a][0] == "ref" else v, "op": op})
        try:
            result = store.transact(facts)
        except TransactError:
            continue
        if result.tx is not None:
            txs.append(result.tx)

    conn = store.conn
    assert read_view(conn, "current") == reference.state(conn)
    for tx in txs:
        assert read_view(conn, "asof", as_of=tx) == reference.state(conn, tx), f"as of {tx}"
    log = conn.execute("select count(*) from fact where a in (select id from attr where ident like 'prop/%%')").fetchone()[0]
    in_history = sum(conn.execute(psycopg.sql.SQL("select count(*) from history.{}").format(
        psycopg.sql.Identifier(i))).fetchone()[0] for i in ATTRS)
    assert in_history == log


def test_tx_column_is_the_asserting_transaction(store):
    store.register_attribute(attr("order/status", "string", doc="Where an order is: open, paid or shipped."))
    first = store.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}])
    order = first.tempids["tmp:o"]
    second = store.transact([{"e": order, "a": "order/status", "v": "paid"}])
    q = 'select v, tx from "order/status" where e = %s'
    with store.conn.transaction():
        store.conn.execute("set local search_path = current")
        assert store.conn.execute(q, (order,)).fetchall() == [("paid", second.tx)]
        store.conn.execute("set local search_path = asof")
        store.conn.execute("select set_config('factstore.as_of', %s, true)", (str(first.tx),))
        assert store.conn.execute(q, (order,)).fetchall() == [("open", first.tx)]
    rows = store.conn.execute('select v, tx, op from history."order/status" where e = %s', (order,)).fetchall()
    assert sorted(rows) == [("open", first.tx, "assert"), ("open", second.tx, "retract"), ("paid", second.tx, "assert")]


def test_views_are_read_only_and_typed(store):
    store.register_attribute(attr("order/total", "decimal", doc="What the customer paid for an order, tax included."))
    order = store.transact([{"e": "tmp:o", "a": "order/total", "v": "99.50"}]).tempids["tmp:o"]
    from decimal import Decimal
    assert store.conn.execute('select v from current."order/total"').fetchall() == [(Decimal("99.50"),)]
    refused = (psycopg.errors.InsufficientPrivilege, psycopg.errors.ObjectNotInPrerequisiteState)
    with pytest.raises(refused):
        store.conn.execute('insert into current."order/total" (e, v, tx) values (%s, 1, 1)', (order,))
    with pytest.raises(refused):
        store.conn.execute('delete from history."order/total"')


def test_excised_values_leave_every_view(store, exciser):
    store.register_attribute(attr("customer/email", "string", doc="Email address a customer signed up with."))
    first = store.transact([{"e": "tmp:c", "a": "customer/email", "v": "ann@example.com"}])
    exciser.excise(first.tempids["tmp:c"])
    assert read_view(store.conn, "current") == reference.state(store.conn)
    assert not store.conn.execute('select * from history."customer/email"').fetchall()
    with store.conn.transaction():
        store.conn.execute("select set_config('factstore.as_of', %s, true)", (str(first.tx),))
        assert not store.conn.execute('select * from asof."customer/email"').fetchall()
        assert not store.conn.execute("select * from asof.facts where v like '%%example.com'").fetchall()


def test_facts_view_now_and_as_of(store):
    store.register_attribute(attr("order/status", "string", doc="Where an order is: open, paid or shipped."))
    first = store.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}])
    order = first.tempids["tmp:o"]
    store.transact([{"e": order, "a": "order/status", "v": "paid"}])
    q = "select a, v from %s.facts where e = %%s"
    assert store.conn.execute(q % "current", (order,)).fetchall() == [("order/status", "paid")]
    with store.conn.transaction():
        store.conn.execute("select set_config('factstore.as_of', %s, true)", (str(first.tx),))
        assert store.conn.execute(q % "asof", (order,)).fetchall() == [("order/status", "open")]


def test_upgrade_rebuilds_the_views(store, store_name):
    from conftest import ADMIN_DSN
    from factstore import admin
    store.register_attribute(attr("order/status", "string", doc="Where an order is: open, paid or shipped."))
    store.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}])
    admin.upgrade_views(ADMIN_DSN, store_name)
    assert store.conn.execute('select v from current."order/status"').fetchall() == [("open",)]
    store.register_attribute(attr("order/note", "string", doc="Free text a merchant wrote on an order."))
    assert store.conn.execute('select count(*) from history."order/note"').fetchone() == (0,)
