import pytest

import reference
from conftest import attr
from factstore import TransactError


@pytest.fixture
def orders(store):
    store.register_attribute([
        attr("shopify/order_id", "string", unique="identity", doc="Shopify's ID for an order."),
        attr("order/status", "string", doc="Where an order is: open, paid, fulfilled, cancelled."),
        attr("order/tag", "string", "many", doc="Labels a merchant put on an order."),
        attr("core/part_of", "ref", "many", doc="The whole this entity belongs to, e.g. a line item's order."),
        attr("core/confidence", "decimal", doc="How sure the writer is, from 0 to 1, about a transaction's facts."),
    ])
    return store


def test_temporary_ids_and_refs_in_one_write(orders):
    result = orders.transact([
        {"e": "tmp:order", "a": "order/status", "v": "open"},
        {"e": "tmp:line", "a": "core/part_of", "v": "tmp:order"},
    ])
    order, line = result.tempids["tmp:order"], result.tempids["tmp:line"]
    assert reference.value(orders.conn, line, "core/part_of") == {order}


def test_cardinality_one_replaces_and_records_the_retraction(orders):
    order = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}]).tempids["tmp:o"]
    result = orders.transact([{"e": order, "a": "order/status", "v": "paid"}])
    assert [(f.v, f.op) for f in result.facts] == [("open", "retract"), ("paid", "assert")]
    assert reference.value(orders.conn, order, "order/status") == {"paid"}


def test_cardinality_many_accumulates(orders):
    order = orders.transact([{"e": "tmp:o", "a": "order/tag", "v": "vip"}]).tempids["tmp:o"]
    orders.transact([{"e": order, "a": "order/tag", "v": "gift"}])
    orders.transact([{"e": order, "a": "order/tag", "v": "vip", "op": "retract"}])
    assert reference.value(orders.conn, order, "order/tag") == {"gift"}


def test_nothing_changed_writes_no_transaction(orders):
    order = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}]).tempids["tmp:o"]
    before = orders.conn.execute("select count(*) from tx").fetchone()[0]
    result = orders.transact([
        {"e": order, "a": "order/status", "v": "open"},
        {"e": order, "a": "order/tag", "v": "never-there", "op": "retract"},
        {"e": "tmp:tx", "a": "core/confidence", "v": "0.9"},
    ])
    assert result.tx is None
    assert result.unchanged == [0, 1, 2]
    assert orders.conn.execute("select count(*) from tx").fetchone()[0] == before


def test_unchanged_facts_are_reported_alongside_changes(orders):
    order = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}]).tempids["tmp:o"]
    result = orders.transact([{"e": order, "a": "order/status", "v": "open"},
                              {"e": order, "a": "order/tag", "v": "vip"}])
    assert result.tx is not None
    assert result.unchanged == [0]


def test_transaction_metadata_goes_on_the_transaction(orders):
    result = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"},
                              {"e": "tmp:tx", "a": "core/confidence", "v": "0.75"}])
    assert result.tempids["tmp:tx"] == result.tx
    assert {str(v) for v in reference.value(orders.conn, result.tx, "core/confidence")} == {"0.75"}


def test_a_later_transaction_can_annotate_an_earlier_one(orders):
    first = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}])
    orders.transact([{"e": first.tx, "a": "core/confidence", "v": "0.5"}])
    assert {str(v) for v in reference.value(orders.conn, first.tx, "core/confidence")} == {"0.5"}


def test_lookup_upserts(orders):
    created = orders.transact([{"e": ["shopify/order_id", "77"], "a": "order/status", "v": "open"}])
    updated = orders.transact([{"e": ["shopify/order_id", "77"], "a": "order/status", "v": "paid"}])
    assert created.lookups[0]["created"] and not updated.lookups[0]["created"]
    assert created.lookups[0]["e"] == updated.lookups[0]["e"]


def test_lookup_as_a_ref_value(orders):
    result = orders.transact([{"e": "tmp:line", "a": "core/part_of", "v": ["shopify/order_id", "78"]}])
    order = result.lookups[0]["e"]
    assert reference.value(orders.conn, order, "shopify/order_id") == {"78"}


def test_identity_value_held_elsewhere_points_at_the_lookup(orders):
    orders.transact([{"e": ["shopify/order_id", "79"], "a": "order/status", "v": "open"}])
    with pytest.raises(TransactError, match=r'already belongs to entity \d+; address it with the lookup'):
        orders.transact([{"e": "tmp:dup", "a": "shopify/order_id", "v": "79"}])


def test_retracting_through_a_lookup_that_finds_nothing_is_an_error(orders):
    with pytest.raises(TransactError, match="no entity has shopify/order_id"):
        orders.transact([{"e": ["shopify/order_id", "missing"], "a": "order/status", "v": "open", "op": "retract"}])


def test_conflicts_inside_one_transaction(orders):
    order = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}]).tempids["tmp:o"]
    with pytest.raises(TransactError, match="cardinality one"):
        orders.transact([{"e": order, "a": "order/status", "v": "paid"},
                         {"e": order, "a": "order/status", "v": "cancelled"}])
    with pytest.raises(TransactError, match="both asserted and retracted"):
        orders.transact([{"e": order, "a": "order/tag", "v": "x"},
                         {"e": order, "a": "order/tag", "v": "x", "op": "retract"}])


def test_every_problem_is_reported_at_once(orders):
    with pytest.raises(TransactError) as rejected:
        orders.transact([{"e": 999_999, "a": "order/status", "v": "open"},
                         {"e": "tmp:o", "a": "order/status", "v": 5},
                         {"e": "tmp:o", "a": "order/colour", "v": "red"},
                         {"e": "tmp:p", "a": "core/part_of", "v": "tmp:nobody"}])
    messages = " | ".join(e["message"] for e in rejected.value.errors)
    assert "entity 999999 does not exist" in messages
    assert "expected a string" in messages
    assert "unknown attribute order/colour" in messages
    assert "tmp:nobody is used as a value but never as an entity" in messages


def test_dry_run_reports_without_writing(orders):
    before = orders.conn.execute("select count(*) from fact").fetchone()[0]
    result = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"},
                              {"e": "tmp:o", "a": "order/colour", "v": "red"},
                              {"e": ["shopify/order_id", "80"], "a": "order/tag", "v": "new"}], dry_run=True)
    assert result.dry_run and result.tx is None
    assert result.unknown_attributes == ["order/colour"]
    assert result.errors == []
    assert ("tmp:o", "order/status", "open", "assert") in [(f.e, f.a, f.v, f.op) for f in result.facts]
    assert result.lookups == [{"lookup": ["shopify/order_id", "80"], "e": ["shopify/order_id", "80"], "created": True}]
    assert orders.conn.execute("select count(*) from fact").fetchone()[0] == before


def test_deprecated_attributes_point_at_their_replacement(orders):
    orders.register_attribute(attr("order/state", "string",
                                   doc="Lifecycle stage of an order, superseding the old status field.",
                                   distinct_from=["order/status"]))
    orders.transact([{"e": ["fs/ident", "order/status"], "a": "fs/replaced_by", "v": ["fs/ident", "order/state"]}])
    with pytest.raises(TransactError, match="order/status is deprecated: use order/state"):
        orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}])
    hits = {a.ident: a for a in orders.search_attributes("order status")}
    assert hits["order/status"].replaced_by == "order/state"


def test_replacement_cycles_are_refused(orders):
    orders.register_attribute(attr("order/state", "string", doc="Lifecycle stage of an order, newer field.",
                                   distinct_from=["order/status"]))
    orders.transact([{"e": ["fs/ident", "order/status"], "a": "fs/replaced_by", "v": ["fs/ident", "order/state"]}])
    with pytest.raises(TransactError, match="makes a cycle"):
        orders.transact([{"e": ["fs/ident", "order/state"], "a": "fs/replaced_by",
                          "v": ["fs/ident", "order/status"]}])


def test_schema_attributes_only_describe_attributes(orders):
    order = orders.transact([{"e": "tmp:o", "a": "order/status", "v": "open"}]).tempids["tmp:o"]
    with pytest.raises(TransactError, match="describes attributes"):
        orders.transact([{"e": order, "a": "fs/doc", "v": "not an attribute"}])
    with pytest.raises(TransactError, match="kernel attribute and cannot change"):
        orders.transact([{"e": ["fs/ident", "fs/doc"], "a": "fs/doc", "v": "rewritten"}])


def test_docs_can_be_improved(orders):
    orders.transact([{"e": ["fs/ident", "order/tag"], "a": "fs/doc",
                      "v": "Labels a merchant put on an order in the Shopify admin."}])
    assert orders.search_attributes("order tag")[0].doc == "Labels a merchant put on an order in the Shopify admin."
