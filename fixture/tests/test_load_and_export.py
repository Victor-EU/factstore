import csv
import json
import mailbox
import os

from factstore_fixture.exports import export
from factstore_fixture.load import load
from factstore_fixture.simulate import Simulation
from factstore_fixture.vocabulary import SHAPES


def test_the_packages_have_every_attribute_the_shapes_name(store):
    registered = {r[0] for r in store.conn.execute("select ident from attr")}
    assert {a for spec in SHAPES.values() for a in spec["always"] + spec.get("often", [])} <= registered


def test_loaded_entities_have_their_shapes(store):
    load(store, Simulation(7), max_orders=3000)
    conn = store.conn
    for shape, spec in SHAPES.items():
        key = spec["always"][0]
        rows = conn.execute(
            "select e from cur where a = (select id from attr where ident = %s) limit 20", (key,)).fetchall()
        assert rows, f"no {shape} loaded"
        for (e,) in rows:
            present = {r[0] for r in conn.execute(
                "select attr.ident from cur join attr on attr.id = cur.a where cur.e = %s", (e,))}
            missing = set(spec["always"]) - present
            assert not missing, f"{shape} {e} lacks {missing}"


def test_loading_again_creates_no_entities(store):
    load(store, Simulation(7), max_orders=2000)
    count = "select count(distinct e) from cur where e not in (select id from tx)"
    before = store.conn.execute(count).fetchone()[0]
    load(store, Simulation(7), max_orders=2000)
    assert store.conn.execute(count).fetchone()[0] == before


def test_exports(tmp_path):
    counts = export(str(tmp_path))
    out = str(tmp_path)

    orders, parents = set(), set()
    with open(os.path.join(out, "shopify", "orders.jsonl")) as fh:
        for line in fh:
            record = json.loads(line)
            if "__parentId" in record:
                parents.add(record["__parentId"])
            else:
                orders.add(record["id"])
    assert parents <= orders and len(orders) == counts["shopify_orders"]

    with open(os.path.join(out, "amazon", "all_orders.txt")) as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    assert len({r["amazon-order-id"] for r in rows}) == counts["amazon_orders"]

    with open(os.path.join(out, "truth", "crosswalk.csv")) as fh:
        crosswalk = list(csv.DictReader(fh))
    assert len(crosswalk) == len(Simulation(7).skus)

    pdfs = os.listdir(os.path.join(out, "supplier_docs"))
    assert len(pdfs) == counts["pdfs"]
    for name in pdfs[:20]:
        data = open(os.path.join(out, "supplier_docs", name), "rb").read()
        assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")

    box = mailbox.mbox(os.path.join(out, "email", "ops_inbox.mbox"))
    assert len(box) == counts["emails"] and all(m["Message-ID"] for m in box)

    with open(os.path.join(out, "truth", "statements.jsonl")) as fh:
        statements = [json.loads(line) for line in fh]
    for s in statements:
        path = s["ref"].split("#")[0].split(" ")[0]
        assert os.path.exists(os.path.join(out, path)), s["ref"]
    assert {s["field"] for s in statements} >= {"etd", "pi_number", "qc_result", "container_no", "eta", "duty_total"}
