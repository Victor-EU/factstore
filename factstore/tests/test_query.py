"""query: one read-only SQL statement over the attribute views."""

import re
import threading
from datetime import timedelta
from decimal import Decimal

import pytest

from conftest import attr
from factstore import QueryError, connect, fs, read, tools


@pytest.fixture
def orders(store):
    store.register_attribute([
        attr("shopify/order_id", "string", unique="identity", doc="Shopify's ID for an order."),
        attr("order/status", "string", doc="Where an order is: open, paid, fulfilled, cancelled."),
        attr("order/total", "decimal", doc="What the customer paid for an order, tax included."),
    ])
    return store


def test_reads_current_state_and_as_of_a_transaction_or_an_instant(orders):
    first = orders.transact([{"e": ["shopify/order_id", "1"], "a": "order/status", "v": "open"}])
    second = orders.transact([{"e": ["shopify/order_id", "1"], "a": "order/status", "v": "paid"}])
    q = 'select s.v from "order/status" s join "shopify/order_id" o using (e) where o.v = \'1\''
    assert orders.query(q).rows == [["paid"]]
    assert orders.query(q, as_of=first.tx).rows == [["open"]]
    result = orders.query(q, as_of=first.at.isoformat())
    assert (result.rows, result.as_of) == ([["open"]], first.tx)
    assert orders.query(q, as_of=(second.at + timedelta(seconds=1)).isoformat()).rows == [["paid"]]


def test_bad_as_of_is_explained(orders):
    with pytest.raises(QueryError, match="no transaction 999999"):
        orders.query("select 1", as_of=999999)
    with pytest.raises(QueryError, match="timezone"):
        orders.query("select 1", as_of="2026-01-01T00:00:00")
    with pytest.raises(QueryError, match="no transaction at or before"):
        orders.query("select 1", as_of="1999-01-01T00:00:00Z")


def test_values_are_typed_and_exact(orders):
    orders.transact([{"e": ["shopify/order_id", "1"], "a": "order/total", "v": "99.50"}])
    result = orders.query('select v from "order/total"')
    assert result.columns == ["v"] and result.rows == [[Decimal("99.50")]]


def test_nothing_a_query_does_can_write(orders, writer):
    for statement in ['insert into public.fact (e, a, v_string, tx, op) values (1, 1, \'x\', 1, true)',
                      "select nextval('entity_seq')",
                      "update public.attr set doc = 'x'"]:
        with pytest.raises(QueryError):
            orders.query(statement)
    with pytest.raises(QueryError, match="multiple commands"):
        orders.query("select 1; delete from public.cur")
    with pytest.raises(QueryError, match="must return rows"):
        orders.query("set role " + writer.dsn.split("user=")[1].split()[0])


def test_session_changes_do_not_outlive_the_query(orders):
    login = orders.query("select session_user").rows[0][0]
    orders.query("select set_config('role', 'none', false), set_config('search_path', 'public', false)")
    assert orders.query("select current_user, current_setting('search_path')").rows == [[login, "current"]]
    latest = orders.query('select max(e) from "fs/at"').rows[0][0]
    assert orders.query("select current_setting('search_path')", as_of=latest).rows == [["asof"]]
    assert orders.query("select current_setting('transaction_read_only')").rows == [["on"]]


def test_a_query_cannot_hold_the_writer_lock(orders):
    orders.query(f"select pg_advisory_lock({fs.WRITER_LOCK})")
    done = threading.Event()

    def write():
        orders.transact([{"e": ["shopify/order_id", "2"], "a": "order/status", "v": "open"}])
        done.set()
    # The write runs on the store's other connection; it would block for ever if the lock survived.
    t = threading.Thread(target=write, daemon=True)
    t.start()
    assert done.wait(10)


def test_slow_queries_are_cancelled(orders):
    with pytest.raises(QueryError, match="longer than 0.2 s"):
        read.execute(orders.reader(), "select pg_sleep(2)", timeout_ms=200)


def test_rows_are_capped_and_truncation_reported(orders):
    result = orders.query("select generate_series(1, 1500) as n")
    assert len(result.rows) == 1000 and result.truncated
    assert not orders.query("select 1").truncated


def test_errors_carry_postgres_hints(orders):
    with pytest.raises(QueryError, match='"order/statuz" does not exist'):
        orders.query('select * from "order/statuz"')


def test_history_and_provenance(orders):
    first = orders.transact([{"e": ["shopify/order_id", "1"], "a": "order/status", "v": "open"}])
    orders.transact([{"e": ["shopify/order_id", "1"], "a": "order/status", "v": "paid"}])
    rows = orders.query('select h.v, h.op, n.v from history."order/status" h'
                        ' join "fs/actor" a on a.e = h.tx join "fs/name" n on n.e = a.v order by h.tx, h.op').rows
    assert rows == [["open", "assert", "test agent"], ["paid", "assert", "test agent"], ["open", "retract", "test agent"]]
    assert orders.query('select tx from "order/status"').rows[0][0] > first.tx


def test_the_recursion_example_in_the_tool_description_works(store):
    store.register_attribute([
        attr("shopify/customer_id", "string", unique="identity", doc="Shopify's ID for a customer account."),
        attr("core/same_as", "ref", doc="The surviving entity this duplicate stands for."),
    ])
    ids = store.transact([{"e": f"tmp:{c}", "a": "shopify/customer_id", "v": c} for c in "abcde"]).tempids
    a, b, c, d, e = (ids[f"tmp:{x}"] for x in "abcde")
    # a <- b <- c, and d -> a: one person with four accounts; e is someone else.
    store.transact([{"e": b, "a": "core/same_as", "v": a}, {"e": c, "a": "core/same_as", "v": b},
                    {"e": d, "a": "core/same_as", "v": a}])
    example = re.search(r"with recursive.*?select e from down", tools.QUERY["description"], re.S).group(0)
    for start in (a, b, c, d):
        assert {r[0] for r in store.query(example.replace("42::bigint", f"{start}::bigint")).rows} == {a, b, c, d}


def test_query_needs_a_connection_string(writer):
    import psycopg
    from factstore import Store
    with pytest.raises(QueryError, match="factstore.connect"):
        Store(psycopg.connect(writer.dsn, autocommit=True)).query("select 1")
    with connect(writer.dsn) as s:
        assert s.query("select 1 as one").rows == [[1]]
