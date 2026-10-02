"""Build plan M3 exit: the packages install on an empty store; installing twice changes nothing;
registering a near-duplicate of a package attribute is refused. Plus factstore-skills (M4): its
shape vocabulary installs like a package, and every package's skills are well-formed."""

import json
import re

import pytest

from conftest import ADMIN_DSN, PACKAGES, new_store, owner
from factstore import RegistrationRefused, admin, connect, packages

CORE = packages.load(PACKAGES / "core")
ECOM_OPS = packages.load(PACKAGES / "ecom-ops")
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
        results = admin.install(ADMIN_DSN, name, [ECOM_OPS, SKILLS])
        for package, result in zip([ECOM_OPS, SKILLS], results):
            assert result.registered == [a["ident"] for a in package.attributes]
        with owner(name) as conn:
            assert registrations(conn) == {"factstore-core": (1, len(CORE.attributes)),
                                           "factstore-ecom-ops": (1, len(ECOM_OPS.attributes)),
                                           "factstore-skills": (1, len(SKILLS.attributes))}
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_they_install_together_in_dependency_order():
    name = new_store(core=False)
    try:
        results = admin.install(ADMIN_DSN, name, [SKILLS, ECOM_OPS, CORE])
        assert [r.package for r in results] == ["factstore-core", "factstore-skills", "factstore-ecom-ops"]
    finally:
        admin.drop_store(ADMIN_DSN, name)


def test_installing_twice_changes_nothing():
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [ECOM_OPS, SKILLS])
        with owner(name) as conn:
            before = snapshot(conn)
            again = admin.install(ADMIN_DSN, name, [CORE, ECOM_OPS, SKILLS])
            assert [r.tx for r in again] == [None, None, None]
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


@pytest.fixture(scope="module")
def agent():
    """A store with both packages, and an agent's credential for it."""
    name = new_store()
    try:
        admin.install(ADMIN_DSN, name, [ECOM_OPS, SKILLS])
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


@pytest.mark.parametrize("package", [CORE, ECOM_OPS, SKILLS], ids=lambda p: p.name)
def test_skills_are_agent_skills(package):
    """Each skill is a SKILL.md with the frontmatter agents load it by: a name and a description."""
    for skill in package.skills:
        text = (package.path / skill).read_text()
        front = re.match(r"---\nname: ([a-z0-9-]+)\ndescription: (.+)\n---\n", text)
        assert front, f"{skill} has no name and description frontmatter"
        assert len(front[1]) <= 64 and 0 < len(front[2]) <= 1024
        assert front[1].startswith(("factstore-", package.name.removeprefix("factstore-")))
