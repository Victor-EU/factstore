"""Build plan M3 exit: the packages install on an empty store; installing twice changes nothing;
registering a near-duplicate of a package attribute is refused. Plus factstore-skills (M4): its
shape vocabulary installs like a package, and every package's skills are well-formed. And
factstore-ecom-index (after M5): the names the slice's catalogue runs chose for themselves are refused."""

import json
import re

import pytest

from conftest import ADMIN_DSN, PACKAGES, new_store, owner
from factstore import RegistrationRefused, admin, connect, packages, server

CORE = packages.load(PACKAGES / "core")
ECOM_OPS = packages.load(PACKAGES / "ecom-ops")
ECOM_INDEX = packages.load(PACKAGES / "ecom-index")
SKILLS = packages.load(PACKAGES.parent / "factstore-skills")


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


def test_each_installs_on_an_empty_store_in_one_transaction():
    name = new_store()
    try:
        results = admin.install(ADMIN_DSN, name, [ECOM_OPS, ECOM_INDEX, SKILLS])
        for package, result in zip([ECOM_OPS, ECOM_INDEX, SKILLS], results):
            assert result.registered == [a["ident"] for a in package.attributes]
        with owner(name) as conn:
            assert registrations(conn) == {"factstore-core": (1, len(CORE.attributes)),
                                           "factstore-ecom-ops": (1, len(ECOM_OPS.attributes)),
                                           "factstore-ecom-index": (1, len(ECOM_INDEX.attributes)),
                                           "factstore-skills": (1, len(SKILLS.attributes))}
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_they_install_together_in_dependency_order():
    name = new_store(core=False)
    try:
        results = admin.install(ADMIN_DSN, name, [ECOM_INDEX, SKILLS, ECOM_OPS, CORE])
        order = [r.package for r in results]
        assert sorted(order) == sorted(p.name for p in (CORE, SKILLS, ECOM_OPS, ECOM_INDEX))
        for p in (SKILLS, ECOM_OPS, ECOM_INDEX):
            assert all(order.index(d) < order.index(p.name) for d in p.depends_on)
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_installing_twice_changes_nothing():
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [ECOM_OPS, ECOM_INDEX, SKILLS])
        with owner(name) as conn:
            before = snapshot(conn)
            again = admin.install(ADMIN_DSN, name, [CORE, ECOM_OPS, ECOM_INDEX, SKILLS])
            assert [r.tx for r in again] == [None, None, None, None]
            assert snapshot(conn) == before
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_ecom_ops_0_2_0_makes_the_house_bill_an_identity(tmp_path):
    """0.1.0 had shipment/hbl as a plain attribute. Upgrading evolves it, as the same actor."""
    v1 = tmp_path / "ecom-ops"
    v1.mkdir()
    raw = json.loads((PACKAGES / "ecom-ops" / "manifest.json").read_text())
    raw.update(version="0.1.0", skills=[], attributes=[{**a, "unique": "none"} if a["ident"] == "shipment/hbl" else a
                                                       for a in raw["attributes"]])
    (v1 / "manifest.json").write_text(json.dumps(raw))
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [packages.load(v1)])
        [result] = admin.install(ADMIN_DSN, name, [ECOM_OPS])
        assert (result.evolved, result.tx) == (["shipment/hbl"], None)
        with owner(name) as conn:
            assert conn.execute("select uniq from attr where ident = 'shipment/hbl'").fetchone() == ("identity",)
            assert registrations(conn)["factstore-ecom-ops"] == (1, len(ECOM_OPS.attributes))
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_ecom_ops_0_3_0_leaves_the_stock_attributes_of_earlier_versions(tmp_path):
    """0.3.0 dropped the stock attributes (stock is derived, design §14). A store that has them from
    an earlier version keeps them, and the new version installs over it writing nothing."""
    v021 = tmp_path / "ecom-ops"
    v021.mkdir()
    raw = json.loads((PACKAGES / "ecom-ops" / "manifest.json").read_text())
    stock = [{"ident": "location/code", "type": "string", "cardinality": "one", "unique": "identity",
              "doc": "Our code for a place stock can be, e.g. 3PL-NJ."},
             {"ident": "inventory/quantity", "type": "decimal", "cardinality": "one",
              "doc": "Units at a stock position when last counted."}]
    raw.update(version="0.2.1", skills=[], attributes=raw["attributes"] + stock)
    (v021 / "manifest.json").write_text(json.dumps(raw))
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [packages.load(v021)])
        [result] = admin.install(ADMIN_DSN, name, [ECOM_OPS])
        assert (result.tx, result.registered, result.evolved) == (None, [], [])
        with owner(name) as conn:
            assert conn.execute("select count(*) from attr where ident in ('location/code', 'inventory/quantity')"
                                ).fetchone() == (2,)
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_ecom_ops_0_4_0_and_ecom_index_0_2_0_add_listings_to_a_store_of_the_versions_before(tmp_path):
    """Amazon listings became records of their own after M6's round 1 (evals/m6): a store with
    ecom-ops 0.3.0 and ecom-index 0.1.0 takes the new versions, registering only what they add."""
    added = {"factstore-ecom-ops": ["listing/sku", "listing/asin"], "factstore-ecom-index": ["line/listing"]}
    old = []
    for package in (ECOM_OPS, ECOM_INDEX):
        raw = json.loads((package.path / "manifest.json").read_text())
        raw.update(version="0.0.9", skills=[], attributes=[a for a in raw["attributes"]
                                                          if a["ident"] not in added[package.name]])
        (tmp_path / package.path.name).mkdir()
        (tmp_path / package.path.name / "manifest.json").write_text(json.dumps(raw))
        old.append(packages.load(tmp_path / package.path.name))
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, old)
        results = admin.install(ADMIN_DSN, name, [ECOM_OPS, ECOM_INDEX])
        assert {r.package: r.registered for r in results} == added
        assert all(r.evolved == [] for r in results)
    finally:
        admin.drop_store(ADMIN_DSN, name)


@pytest.fixture(scope="module")
def agent():
    """A store with every package, and an agent's credential for it."""
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [ECOM_OPS, ECOM_INDEX, SKILLS])
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
    # The ontology skill's vocabulary. Synonyms (shape/label, shape/description) pass, as in M3.
    ("shape/shape_name", "string", "Confirmed name of a shape.", "shape/name"),
    ("entity_type/name", "string", "Name of a kind of thing the store holds, e.g. Purchase order.", "shape/name"),
    ("shape/attributes", "ref", "Attributes every entity of a shape carries.", "shape/signature"),
    ("shape/doc_text", "string", "One line describing a shape.", "shape/doc"),
    # factstore-ecom-index. The first five are names the slice's catalogue runs registered before it existed (M5).
    ("amazon/order_line_key", "string", "One item line of an Amazon order, keyed by order ID and seller SKU.",
     "amazon/order_line"),
    ("amazon/inbound_shipment_id", "string", "Amazon's ID for an FBA inbound shipment.", "amazon/fba_shipment_id"),
    ("tpl/receipt_line_key", "string", "One line of a 3PL receipt, as receipt number and item code.",
     "tpl/receipt_line"),
    ("tpl/outbound_key", "string", "One line of the 3PL's outbound file, as order reference and item code.",
     "tpl/outbound_line"),
    ("quickbooks/vendor_name", "string", "Vendor name in QuickBooks.", "quickbooks/vendor"),
    ("shopify/order_number", "string", "Shopify order name such as #18301.", "shopify/order_name"),
    # core 0.2.0
    ("document/issue_date", "date", "Date printed on a document.", "document/issued_at"),
    # ecom-ops 0.4.0 and ecom-index 0.2.0: Amazon listings
    ("amazon/listing_asin", "ref", "ASIN an Amazon listing is listed under.", "listing/asin"),
    ("order_line/listing", "ref", "Marketplace listing an order line names.", "line/listing"),
]


@pytest.mark.parametrize("ident, type_, doc, duplicates", NEAR_DUPLICATES, ids=[c[0] for c in NEAR_DUPLICATES])
def test_a_near_duplicate_of_a_package_attribute_is_refused(agent, ident, type_, doc, duplicates):
    with pytest.raises(RegistrationRefused) as refused:
        agent.register_attribute({"ident": ident, "type": type_, "cardinality": "one", "doc": doc})
    assert duplicates in [m.ident for m in refused.value.near_matches[ident]]


def test_distinct_from_names_only_the_package_and_its_dependencies():
    core = {a["ident"] for a in CORE.attributes}
    assert all(d in core for a in CORE.attributes for d in a.get("distinct_from", []))
    for package in (ECOM_OPS, SKILLS):
        assert package.depends_on == ("factstore-core",)
        known = core | {a["ident"] for a in package.attributes}
        assert all(d in known for a in package.attributes for d in a.get("distinct_from", []))
    assert ECOM_INDEX.depends_on == ("factstore-core", "factstore-ecom-ops")
    known = core | {a["ident"] for p in (ECOM_OPS, ECOM_INDEX) for a in p.attributes}
    assert all(d in known for a in ECOM_INDEX.attributes for d in a.get("distinct_from", []))


@pytest.mark.parametrize("package", [CORE, ECOM_OPS, SKILLS], ids=lambda p: p.name)
def test_skills_are_agent_skills(package):
    """Each skill is a SKILL.md with the frontmatter agents load it by, a name and a description,
    and the package's license, since a skill is often copied on its own."""
    for skill in package.skills:
        text = (package.path / skill).read_text()
        front = re.match(r"---\nname: ([a-z0-9-]+)\ndescription: (.+)\nlicense: (.+)\n---\n", text)
        assert front, f"{skill} has no name, description and license frontmatter"
        assert len(front[1]) <= 64 and 0 < len(front[2]) <= 1024
        assert front[1].startswith(("factstore-", package.name.removeprefix("factstore-")))
        assert front[3] == package.license == "MIT"


def test_core_0_3_0_adds_personal_to_a_store_of_0_2_0(tmp_path):
    """core/personal came after M6's round 5 (design open question 7): a store with core 0.2.0
    takes 0.3.0, registering only it."""
    v2 = tmp_path / "core"
    v2.mkdir()
    raw = json.loads((PACKAGES / "core" / "manifest.json").read_text())
    raw.update(version="0.2.0", attributes=[a for a in raw["attributes"] if a["ident"] != "core/personal"])
    (v2 / "manifest.json").write_text(json.dumps(raw))
    name = new_store(core=False)
    try:
        admin.install(ADMIN_DSN, name, [packages.load(v2)])
        [result] = admin.install(ADMIN_DSN, name, [CORE])
        assert (result.registered, result.evolved) == (["core/personal"], [])
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_the_business_allows_an_attribute_for_personal_data_and_withdraws_it():
    """The steps in packages/README.md. The owner allows an attribute with their own credential, so
    the log says who; agents find it with the query in the server's instructions; withdrawing
    retracts the allowance and excises every value, history included."""
    listed = re.search(r'List them with: (select .+? where p\.v)\.', " ".join(server.INSTRUCTIONS.split()))[1]
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [ECOM_OPS])
        agent = connect(admin.create_actor(ADMIN_DSN, name, "agent").dsn)
        assert agent.query(listed).rows == []

        boss = admin.create_actor(ADMIN_DSN, name, "owner")
        owner_ = connect(boss.dsn)
        allowance = {"e": ["fs/ident", "supplier/contact_name"], "a": "core/personal", "v": True}
        owner_.transact([allowance])
        assert agent.query(listed).rows == [["supplier/contact_name"]]
        by = agent.query('select n.v from "core/personal" p join "fs/actor" a on a.e = p.tx'
                         ' join "fs/name" n on n.e = a.v').rows
        assert by == [["owner"]]

        agent.transact([{"e": ["supplier/code", "NBBW"], "a": "supplier/contact_name", "v": "Lily Example"}])
        agent.transact([{"e": ["supplier/code", "NBBW"], "a": "supplier/contact_name", "v": "Lily Example-Wu"}])

        owner_.transact([{**allowance, "op": "retract"}])
        exciser = connect(admin.create_credential(ADMIN_DSN, name, boss.actor, excise=True).dsn)
        while held := exciser.query('select distinct e from history."supplier/contact_name"').rows:
            for (e,) in held:
                exciser.excise(e, ["supplier/contact_name"])
        assert agent.query(listed).rows == []
        assert agent.query('select count(*) from history."supplier/contact_name"').rows == [[0]]
    finally:
        admin.drop_store(ADMIN_DSN, name)
