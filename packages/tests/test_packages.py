"""Build plan M3 exit: both packages install on an empty store; installing twice changes nothing;
registering a near-duplicate of a package attribute is refused."""

import pytest

from conftest import ADMIN_DSN, PACKAGES, new_store, owner
from factstore import RegistrationRefused, admin, connect, packages

CORE = packages.load(PACKAGES / "core")
ECOM_OPS = packages.load(PACKAGES / "ecom-ops")


def registrations(conn) -> dict[str, tuple[int, int]]:
    """Per actor: the transactions it registered attributes in, and how many attributes."""
    rows = conn.execute("""
        select n.v_string, count(distinct f.tx), count(*) from fact f join tx on tx.id = f.tx
        join cur n on n.e = tx.actor and n.a = 10
        where f.a = 1 and not starts_with(f.v_string, 'fs/') group by 1""").fetchall()
    return {name: (txs, n) for name, txs, n in rows}


def snapshot(conn) -> tuple:
    return conn.execute("select (select max(id) from tx), (select count(*) from fact),"
                        " (select count(*) from actor_login)").fetchone()


def test_both_install_on_an_empty_store_each_in_one_transaction():
    name = new_store()
    try:
        [result] = admin.install(ADMIN_DSN, name, [ECOM_OPS])
        assert result.registered == [a["ident"] for a in ECOM_OPS.attributes]
        with owner(name) as conn:
            assert registrations(conn) == {"factstore-core": (1, len(CORE.attributes)),
                                           "factstore-ecom-ops": (1, len(ECOM_OPS.attributes))}
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_they_install_together_in_dependency_order():
    name = new_store(core=False)
    try:
        results = admin.install(ADMIN_DSN, name, [ECOM_OPS, CORE])
        assert [r.package for r in results] == ["factstore-core", "factstore-ecom-ops"]
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_installing_twice_changes_nothing():
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [ECOM_OPS])
        with owner(name) as conn:
            before = snapshot(conn)
            again = admin.install(ADMIN_DSN, name, [CORE, ECOM_OPS])
            assert [r.tx for r in again] == [None, None]
            assert snapshot(conn) == before
    finally:
        admin.drop_store(ADMIN_DSN, name)


@pytest.fixture(scope="module")
def agent():
    """A store with both packages, and an agent's credential for it."""
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [ECOM_OPS])
        cred = admin.create_actor(ADMIN_DSN, name, "test agent")
        with connect(cred.dsn) as store:
            yield store
    finally:
        admin.drop_store(ADMIN_DSN, name)


# What an agent might register instead of reusing a package attribute, and the attribute it duplicates.
NEAR_DUPLICATES = [
    ("po/po_number", "string", "Purchase order number.", "po/number"),
    ("po/revised_etd", "date", "Revised ETD after a supplier delay.", "po/etd"),
    ("supplier/supplier_code", "string", "Our code for a supplier.", "supplier/code"),
    ("supplier/chinese_name", "string", "Chinese name of a supplier.", "supplier/name"),
    ("shipment/booking_number", "string", "Booking number from the forwarder.", "shipment/booking_no"),
    ("shipment/container_number", "string", "Container number.", "shipment/container_no"),
    ("shipment/eta_date", "instant", "Expected arrival at the destination port.", "shipment/eta"),
    ("shipment/freight", "decimal", "Freight cost of a shipment.", "shipment/freight_cost"),
    ("customs/duty_amount", "decimal", "Duty paid on a customs entry.", "customs/duty"),
    ("amazon/asin_code", "string", "ASIN of a product on Amazon.", "amazon/asin"),
    ("shopify/variant", "string", "Shopify product variant ID.", "shopify/variant_id"),
    # The core conventions, which only work if every namespace reuses them.
    ("order/part_of", "ref", "The order this line belongs to.", "core/part_of"),
    ("po/currency", "string", "Currency of a purchase order.", "core/currency"),
    ("invoice/currency", "string", "ISO 4217 currency code of an invoice.", "core/currency"),
    ("core/source", "string", "Which system is authoritative for an attribute.", "core/authoritative_source"),
]


@pytest.mark.parametrize("ident, type_, doc, duplicates", NEAR_DUPLICATES, ids=[c[0] for c in NEAR_DUPLICATES])
def test_a_near_duplicate_of_a_package_attribute_is_refused(agent, ident, type_, doc, duplicates):
    with pytest.raises(RegistrationRefused) as refused:
        agent.register_attribute({"ident": ident, "type": type_, "cardinality": "one", "doc": doc})
    assert duplicates in [m.ident for m in refused.value.near_matches[ident]]


def test_distinct_from_names_only_the_package_and_its_dependencies():
    known = {a["ident"] for a in CORE.attributes}
    assert all(d in known for a in CORE.attributes for d in a.get("distinct_from", []))
    known |= {a["ident"] for a in ECOM_OPS.attributes}
    assert ECOM_OPS.depends_on == ("factstore-core",)
    assert all(d in known for a in ECOM_OPS.attributes for d in a.get("distinct_from", []))
