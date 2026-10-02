import pytest

from conftest import attr


@pytest.fixture
def orders(store):
    store.register_attribute([
        attr("shopify/order_id", "string", unique="identity", doc="Shopify's ID for an order."),
        attr("order/total", "decimal", doc="What the customer paid for an order, tax included."),
        attr("order/tag", "string", "many", doc="Labels a merchant put on an order."),
        attr("line/sku_code", "string", doc="Our SKU code on one line of an order."),
        attr("core/part_of", "ref", "many", doc="The whole this entity belongs to, e.g. a line item's order."),
    ])
    store.transact([
        {"e": "tmp:o1", "a": "shopify/order_id", "v": "1"}, {"e": "tmp:o1", "a": "order/total", "v": "10"},
        {"e": "tmp:o1", "a": "order/tag", "v": "vip"}, {"e": "tmp:o1", "a": "order/tag", "v": "gift"},
        {"e": "tmp:o2", "a": "shopify/order_id", "v": "2"}, {"e": "tmp:o2", "a": "order/total", "v": "20"},
        {"e": "tmp:o3", "a": "shopify/order_id", "v": "3"},
        {"e": "tmp:l1", "a": "line/sku_code", "v": "A"}, {"e": "tmp:l1", "a": "core/part_of", "v": "tmp:o1"},
        {"e": "tmp:l2", "a": "line/sku_code", "v": "B"}, {"e": "tmp:l2", "a": "core/part_of", "v": "tmp:o2"},
        {"e": "tmp:l3", "a": "line/sku_code", "v": "C"}, {"e": "tmp:l3", "a": "core/part_of", "v": "tmp:o2"},
    ])
    return store


def by_attrs(stats):
    return {tuple(s.attributes): s for s in stats.signatures}


def test_signatures_count_entities_by_attribute_set(orders):
    stats = orders.stats()
    sigs = by_attrs(stats)
    assert sigs[("order/tag", "order/total", "shopify/order_id")].entities == 1
    assert sigs[("order/total", "shopify/order_id")].entities == 1
    assert sigs[("shopify/order_id",)].entities == 1
    assert sigs[("core/part_of", "line/sku_code")].entities == 3
    assert stats.entities == 6
    assert [s.entities for s in stats.signatures] == sorted((s.entities for s in stats.signatures), reverse=True)


def test_usage_counts_entities_and_values(orders):
    usage = {a.ident: a for a in orders.stats().attributes}
    assert (usage["order/tag"].entities, usage["order/tag"].values) == (1, 2)
    assert (usage["shopify/order_id"].entities, usage["shopify/order_id"].values) == (3, 3)


def test_refs_connect_signatures(orders):
    stats = orders.stats()
    sigs = by_attrs(stats)
    lines = sigs[("core/part_of", "line/sku_code")].id
    links = {(r.attribute, r.source, r.target): r.count for r in stats.refs}
    assert links == {
        ("core/part_of", lines, sigs[("order/tag", "order/total", "shopify/order_id")].id): 1,
        ("core/part_of", lines, sigs[("order/total", "shopify/order_id")].id): 2,
    }


def test_kernel_bookkeeping_is_left_out_unless_asked(orders):
    assert not any(a.ident.startswith("fs/") for a in orders.stats().attributes)
    assert all(any(not i.startswith("fs/") for i in s.attributes) for s in orders.stats().signatures)
    with_kernel = orders.stats(include_kernel=True)
    assert any(s.attributes == ["fs/actor", "fs/at"] for s in with_kernel.signatures)  # transactions


def test_retracted_values_do_not_count(orders):
    orders.transact([{"e": ["shopify/order_id", "1"], "a": "order/tag", "v": "vip", "op": "retract"},
                     {"e": ["shopify/order_id", "1"], "a": "order/tag", "v": "gift", "op": "retract"}])
    sigs = by_attrs(orders.stats())
    assert ("order/tag", "order/total", "shopify/order_id") not in sigs
    assert sigs[("order/total", "shopify/order_id")].entities == 2


def test_deprecated_attributes_count_under_their_replacement(orders):
    orders.register_attribute(attr("line/sku", "string", doc="SKU code we sell a line's product under.",
                                   distinct_from=["line/sku_code"]))
    orders.transact([{"e": "tmp:l4", "a": "line/sku", "v": "D"}, {"e": "tmp:l4", "a": "core/part_of", "v": ["shopify/order_id", "3"]},
                     {"e": ["fs/ident", "line/sku_code"], "a": "fs/replaced_by", "v": ["fs/ident", "line/sku"]}])
    stats = orders.stats()
    usage = {a.ident: a for a in stats.attributes}
    assert "line/sku_code" not in usage
    assert usage["line/sku"].entities == 4 and usage["line/sku"].includes == ["line/sku_code"]
    assert by_attrs(stats)[("core/part_of", "line/sku")].entities == 4


def test_namespaces_and_limit(orders):
    stats = orders.stats(namespaces=["line"])
    assert [s.attributes for s in stats.signatures] == [["core/part_of", "line/sku_code"]]
    assert {a.ident for a in stats.attributes} == {"line/sku_code"}
    limited = orders.stats(limit=1)
    assert len(limited.signatures) == 1
    assert limited.omitted_signatures == 3 and limited.omitted_entities == 3
    assert not limited.refs  # the lines' orders are beyond the limit
