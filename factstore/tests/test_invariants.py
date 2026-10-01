"""The M1 exit tests from the build plan, numbered as there."""

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import reference
from conftest import attr


def run_threads(target, n):
    """Run target(i) on n threads; re-raise the first failure instead of letting a thread die quietly."""
    failures = []

    def guarded(i):
        try:
            target(i)
        except BaseException as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    threads = [threading.Thread(target=guarded, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if failures:
        raise failures[0]
from factstore import ExcisionError, PermissionDenied, RegistrationRefused, TransactError, connect


# 1. Updating or deleting a fact as the application role fails.
def test_1_facts_cannot_be_updated_or_deleted(store, owner_conn):
    store.register_attribute(attr("note/text", "string"))
    store.transact([{"e": "tmp:n", "a": "note/text", "v": "first"}])

    for statement in ("update fact set op = not op", "delete from fact", "truncate fact"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            store.conn.execute(statement)

    # Even the owner, which Postgres privileges would allow, is stopped by the triggers.
    for statement in ("update fact set op = not op", "delete from fact", "truncate fact"):
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            owner_conn.execute(statement)


# 2. After random assertions and retractions, current state equals the reference reader.
ENTITIES = 3
ATTRS = {"prop/one": "one", "prop/many": "many"}
fact_ops = st.lists(
    st.tuples(st.integers(0, ENTITIES - 1), st.sampled_from(sorted(ATTRS)), st.sampled_from("abcd"),
              st.sampled_from(["assert", "retract"])),
    min_size=1, max_size=6)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(batches=st.lists(fact_ops, min_size=1, max_size=8))
def test_2_current_state_equals_reference_reader(store, batches):
    # Hypothesis runs every example against the same store; register once.
    store.register_attribute([attr("prop/one", "string", "one", "Single-valued property for the property test."),
                              attr("prop/many", "string", "many", "Set-valued property, for checking folds.")])
    seed = store.transact([{"e": f"tmp:{i}", "a": "prop/one", "v": "seed"} for i in range(ENTITIES)])
    ids = [seed.tempids[f"tmp:{i}"] for i in range(ENTITIES)]

    snapshots = {}
    for batch in batches:
        facts = [{"e": ids[e], "a": a, "v": v, "op": op} for e, a, v, op in batch]
        try:
            result = store.transact(facts)
        except TransactError:
            continue  # e.g. two values for a cardinality-one attribute; nothing was written
        if result.tx is not None:
            snapshots[result.tx] = reference.state(store.conn, result.tx)
        now = reference.state(store.conn)
        assert reference.current_table(store.conn) == now
        one = reference.attr_id(store.conn, "prop/one")
        assert all(len(vs) == 1 for (e, a), vs in now.items() if a == one), "cardinality one holds two values"

    # History never changes: every earlier state is still what it was.
    for tx, snapshot in snapshots.items():
        assert reference.state(store.conn, tx) == snapshot


# 3. With 20 concurrent writers, transaction IDs follow commit order and as-of reads are stable.
def test_3_transaction_ids_follow_commit_order(store, writer):
    store.register_attribute(attr("counter/value", "decimal", doc="Running count written by a load test."))
    writers, per_writer = 20, 15
    done = threading.Event()
    reads: list[tuple[int, dict]] = []

    def write(n):
        with connect(writer.dsn) as s:
            for i in range(per_writer):
                s.transact([{"e": f"tmp:{n}", "a": "counter/value", "v": str(n * 1000 + i)}])

    def read():
        with psycopg.connect(writer.dsn, autocommit=True) as conn:
            while not done.is_set():
                with conn.transaction():
                    conn.execute("set transaction isolation level repeatable read")
                    latest = conn.execute("select max(id) from tx").fetchone()[0]
                    reads.append((latest, reference.state(conn, latest)))

    reader = threading.Thread(target=read)
    reader.start()
    try:
        run_threads(write, writers)
    finally:
        done.set()
        reader.join()
    written = store.conn.execute("select count(*) from fact where a = %s and op",
                                 (reference.attr_id(store.conn, "counter/value"),)).fetchone()[0]
    assert written == writers * per_writer

    rows = store.conn.execute("select id, pg_xact_commit_timestamp(xmin), at from tx order by id").fetchall()
    commit_times = [r[1] for r in rows]
    assert commit_times == sorted(commit_times), "a later transaction ID committed earlier"
    stamps = [r[2] for r in rows]
    assert all(a < b for a, b in zip(stamps, stamps[1:])), "fs/at must increase with transaction ID"

    assert len(reads) > 1
    for latest, seen in reads:
        assert reference.state(store.conn, latest) == seen, f"as-of {latest} changed after it was read"


# 4. 20 concurrent transacts using the same lookup create exactly one entity.
def test_4_concurrent_lookups_create_one_entity(store, writer):
    store.register_attribute([attr("shopify/order_id", "string", unique="identity", doc="Shopify's ID for an order."),
                              attr("order/note", "string", doc="Free-text note a person left on the order.")])
    barrier = threading.Barrier(20)
    results = []

    def write(n):
        with connect(writer.dsn) as s:
            barrier.wait()
            results.append(s.transact([{"e": ["shopify/order_id", "1234"], "a": "order/note", "v": f"from {n}"}]))

    run_threads(write, 20)

    assert len(results) == 20
    entities = {r.lookups[0]["e"] for r in results}
    assert len(entities) == 1
    assert sum(r.lookups[0]["created"] for r in results) == 1
    holders = store.conn.execute(
        "select count(distinct e) from cur where a = %s and v_string = '1234'",
        (reference.attr_id(store.conn, "shopify/order_id"),)).fetchone()[0]
    assert holders == 1


# 5. A payload containing fs/actor or fs/at is rejected; the kernel stamps them.
def test_5_actor_and_time_are_stamped_by_the_kernel(store, writer):
    store.register_attribute(attr("note/text", "string"))
    for ident, value in (("fs/actor", 1), ("fs/at", "2000-01-01T00:00:00Z")):
        with pytest.raises(TransactError, match="written by the kernel only"):
            store.transact([{"e": "tmp:n", "a": "note/text", "v": "x"}, {"e": "tmp:tx", "a": ident, "v": value}])

    result = store.transact([{"e": "tmp:n", "a": "note/text", "v": "hello"}])
    assert reference.value(store.conn, result.tx, "fs/actor") == {writer.actor}
    assert reference.value(store.conn, result.tx, "fs/at") == {result.at}

    # Straight SQL cannot forge them either: the trigger overwrites the claimed actor and time...
    actor, at = store.conn.execute(
        "insert into tx (id, actor, at) values (nextval('entity_seq'), 1, '2000-01-01') returning actor, at"
    ).fetchone()
    assert actor == writer.actor
    assert at > datetime.now(timezone.utc) - timedelta(minutes=5)
    # ...and refuses fs/actor facts written directly.
    with pytest.raises(psycopg.errors.RaiseException, match="kernel only"):
        store.conn.execute("insert into fact (e, a, v_ref, tx, op) values (%s, 8, 1, %s, true)",
                           (result.tx, result.tx))


# 6. Decimals round-trip exactly; an instant without a timezone is rejected.
def test_6_exact_types(store):
    store.register_attribute([attr("invoice/total", "decimal", doc="Invoice total in the invoice currency."),
                              attr("shipment/eta", "instant", doc="Expected arrival at the destination port."),
                              attr("invoice/issued", "date", doc="Calendar date printed on an invoice.")])
    amounts = ["0.1", "99.50", "1234567890.123456789012345678", Decimal("0.30")]
    result = store.transact([{"e": f"tmp:{i}", "a": "invoice/total", "v": v} for i, v in enumerate(amounts)])
    for i, v in enumerate(amounts):
        (stored,) = reference.value(store.conn, result.tempids[f"tmp:{i}"], "invoice/total")
        assert str(stored) == str(v)

    with pytest.raises(TransactError, match="never floats"):
        store.transact([{"e": "tmp:x", "a": "invoice/total", "v": 0.1}])
    with pytest.raises(TransactError, match="no timezone"):
        store.transact([{"e": "tmp:x", "a": "shipment/eta", "v": "2026-10-01T09:30:00"}])
    with pytest.raises(TransactError, match="calendar date"):
        store.transact([{"e": "tmp:x", "a": "invoice/issued", "v": datetime(2026, 10, 1, tzinfo=timezone.utc)}])

    eta = store.transact([{"e": "tmp:s", "a": "shipment/eta", "v": "2026-10-01T09:30:00+08:00"}])
    (stored,) = reference.value(store.conn, eta.tempids["tmp:s"], "shipment/eta")
    assert stored == datetime(2026, 10, 1, 1, 30, tzinfo=timezone.utc)


# 7. A near-duplicate registration is refused, accepted with distinct_from, and the statement is in the log.
def test_7_near_duplicates_need_distinct_from(store):
    store.register_attribute(attr("customer/email", "string", doc="Email address of a customer."))
    near = attr("customer/e_mail", "string", doc="Email address of a customer, as typed at checkout.")

    with pytest.raises(RegistrationRefused) as refused:
        store.register_attribute(near)
    assert [m.ident for m in refused.value.near_matches["customer/e_mail"]] == ["customer/email"]
    assert store.search_attributes("customer/e_mail")[0].ident == "customer/email"

    result = store.register_attribute({**near, "distinct_from": ["customer/email"]})
    assert result.registered == ["customer/e_mail"]
    new_id = reference.attr_id(store.conn, "customer/e_mail")
    assert reference.value(store.conn, new_id, "fs/distinct_from") == {
        reference.attr_id(store.conn, "customer/email")}


# 8. Attributes change in one direction only.
def test_8_attribute_evolution(store, owner_conn):
    store.register_attribute([attr("item/tag", "string", doc="Label someone put on an item."),
                              attr("item/code", "string", doc="Factory code for an item.")])
    tag = ["fs/ident", "item/tag"]

    with pytest.raises(TransactError, match="set by register_attribute"):
        store.transact([{"e": tag, "a": "fs/type", "v": "decimal"}])

    item = store.transact([{"e": "tmp:i", "a": "item/tag", "v": "red"}]).tempids["tmp:i"]
    store.transact([{"e": tag, "a": "fs/cardinality", "v": "many"}])
    store.transact([{"e": item, "a": "item/tag", "v": "large"}])
    assert reference.value(store.conn, item, "item/tag") == {"red", "large"}
    with pytest.raises(TransactError, match="one to many only"):
        store.transact([{"e": tag, "a": "fs/cardinality", "v": "one"}])

    pair = store.transact([{"e": "tmp:a", "a": "item/code", "v": "A100"},
                           {"e": "tmp:b", "a": "item/code", "v": "A100"}]).tempids
    code = ["fs/ident", "item/code"]
    with pytest.raises(TransactError, match="cannot become an identity"):
        store.transact([{"e": code, "a": "fs/unique", "v": "identity"}])
    store.transact([{"e": pair["tmp:b"], "a": "item/code", "v": "A100", "op": "retract"}])
    store.transact([{"e": code, "a": "fs/unique", "v": "identity"}])
    found = store.transact([{"e": ["item/code", "A100"], "a": "item/tag", "v": "found"}])
    assert found.lookups == [{"lookup": ["item/code", "A100"], "e": pair["tmp:a"], "created": False}]

    # Postgres holds the same line if the kernel is bypassed.
    with pytest.raises(psycopg.errors.RaiseException, match="never changes"):
        owner_conn.execute("update attr set type = 'decimal' where ident = 'item/tag'")
    with pytest.raises(psycopg.errors.RaiseException, match="one to many only"):
        owner_conn.execute("update attr set cardinality = 'one' where ident = 'item/tag'")


# 9. Excision removes the values from the log, current state and every as-of read, and records itself.
def test_9_excision(store, exciser):
    store.register_attribute([attr("customer/name", "string", doc="Full name of a customer."),
                              attr("customer/email", "string", doc="Email address of a customer."),
                              attr("shopify/customer_id", "string", unique="identity",
                                   doc="Shopify's ID for a customer.")])
    first = store.transact([{"e": ["shopify/customer_id", "42"], "a": "customer/name", "v": "Ann Lee"},
                            {"e": ["shopify/customer_id", "42"], "a": "customer/email", "v": "ann@example.com"}])
    person = first.lookups[0]["e"]
    second = store.transact([{"e": person, "a": "customer/name", "v": "Anne Lee"}])
    assert reference.state(store.conn, first.tx)[(person, reference.attr_id(store.conn, "customer/name"))] == {"Ann Lee"}

    with pytest.raises(PermissionDenied):
        store.excise(person)

    excision = exciser.excise(["shopify/customer_id", "42"])

    conn = store.conn
    assert conn.execute("select count(*) from fact where e = %s", (person,)).fetchone()[0] == 0
    assert conn.execute("select count(*) from cur where e = %s", (person,)).fetchone()[0] == 0
    assert conn.execute("select count(*) from ident where e = %s", (person,)).fetchone()[0] == 0
    for tx in (first.tx, second.tx, excision):
        assert not any(e == person for e, _ in reference.state(conn, tx))
    assert reference.value(conn, excision, "fs/excised_entity") == {person}
    leaked = conn.execute("select count(*) from fact where tx = %s and v_string like '%%Ann%%'", (excision,))
    assert leaked.fetchone()[0] == 0

    # The person is gone: the lookup no longer finds them.
    with pytest.raises(ExcisionError, match="no entity has"):
        exciser.excise(["shopify/customer_id", "42"])


def test_9b_excision_narrowed_to_attributes(store, exciser):
    store.register_attribute([attr("customer/name", "string", doc="Full name of a customer."),
                              attr("customer/email", "string", doc="Email address of a customer.")])
    person = store.transact([{"e": "tmp:p", "a": "customer/name", "v": "Ann Lee"},
                             {"e": "tmp:p", "a": "customer/email", "v": "ann@example.com"}]).tempids["tmp:p"]

    excision = exciser.excise(person, ["customer/email"])

    assert reference.value(store.conn, person, "customer/name") == {"Ann Lee"}
    assert reference.value(store.conn, person, "customer/email") == frozenset()
    assert reference.value(store.conn, excision, "fs/excised_attribute") == {
        reference.attr_id(store.conn, "customer/email")}

    with pytest.raises(ExcisionError, match="is an attribute"):
        exciser.excise(reference.attr_id(store.conn, "customer/name"))
