"""Vocabulary packages: manifests, and installing them in one registration each."""

import json
import re

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from conftest import ADMIN_DSN
from factstore import RegistrationRefused, TransactError, admin, cli, packages
from factstore.packages import PackageError


def manifest(tmp_path, name, attributes, depends_on=(), **extra):
    directory = tmp_path / name
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({
        "name": name, "version": "0.1.0", "doc": f"Test package {name}.", "depends_on": list(depends_on),
        "skills": [], "attributes": attributes, **extra}))
    return directory


def spec(ident, type_="string", doc=None, **extra):
    return {"ident": ident, "type": type_, "cardinality": "one", "doc": doc or f"Test attribute {ident}.", **extra}


ORDERS = [spec("order/number", unique="identity", doc="Our number for a sales order, e.g. SO-1042."),
          spec("order/placed_at", "instant", doc="When the customer placed an order."),
          spec("order/total", "decimal", doc="What the customer paid for an order, tax included.")]
LINES = [spec("order_line/key", unique="identity", doc="An order line, as order number and line number."),
         spec("order_line/quantity", "decimal", doc="Units ordered on one line of a sales order.")]


@pytest.fixture
def db(store_name):
    with psycopg.connect(make_conninfo(ADMIN_DSN, dbname=store_name), autocommit=True) as conn:
        yield conn


def actors(db):
    return {name: e for e, name in db.execute("select e, v_string from cur where a = 10")}


def last_tx(db):
    return db.execute("select max(id) from tx").fetchone()[0]


def test_a_package_registers_in_one_transaction_as_an_actor_named_after_it(tmp_path, store_name, db):
    [result] = admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path, "test-orders", ORDERS))])
    assert result.registered == ["order/number", "order/placed_at", "order/total"]
    writers = db.execute("select distinct tx.actor from fact join tx on tx.id = fact.tx where fact.tx = %s",
                         (result.tx,)).fetchall()
    assert writers == [(actors(db)["test-orders"],)]
    assert packages.installed(db) == {"test-orders"}


def test_installing_again_writes_nothing(tmp_path, store_name, db):
    package = packages.load(manifest(tmp_path, "test-orders", ORDERS))
    admin.install(ADMIN_DSN, store_name, [package])
    before = last_tx(db), actors(db)
    [again] = admin.install(ADMIN_DSN, store_name, [package])
    assert (again.tx, again.registered, again.existing) == (None, [], [s["ident"] for s in ORDERS])
    assert (last_tx(db), actors(db)) == before


def test_a_new_version_registers_only_what_it_adds_as_the_same_actor(tmp_path, store_name, db):
    admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path, "test-orders", ORDERS[:2]))])
    (tmp_path / "v2").mkdir()
    [result] = admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path / "v2", "test-orders", ORDERS))])
    assert result.registered == ["order/total"] and result.existing == ["order/number", "order/placed_at"]
    assert list(actors(db)).count("test-orders") == 1


def test_a_new_version_may_make_an_attribute_many_or_identity(tmp_path, store_name, db):
    admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path, "test-orders", ORDERS))])
    v2 = [spec("order/placed_at", "instant", doc="When the customer placed an order."),
          spec("order/number", unique="identity", doc="Our number for a sales order, e.g. SO-1042."),
          {**spec("order/total", "decimal", doc="What the customer paid for an order, tax included."),
           "cardinality": "many", "unique": "identity"},
          spec("order/channel", doc="Sales channel an order came through.")]
    (tmp_path / "v2").mkdir()
    [result] = admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path / "v2", "test-orders", v2))])
    assert result.evolved == ["order/total"] and result.registered == ["order/channel"]
    assert result.evolve_tx < result.tx
    assert db.execute("select cardinality, uniq from attr where ident = 'order/total'").fetchone() == ("many", "identity")
    writers = db.execute("select distinct actor from tx where id in (%s, %s)", (result.evolve_tx, result.tx)).fetchall()
    assert writers == [(actors(db)["test-orders"],)]


def test_an_evolution_the_values_refuse_writes_nothing(tmp_path, store, store_name, db):
    admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path, "test-orders", ORDERS))])
    store.transact([{"e": f"tmp:{i}", "a": "order/total", "v": "10.00"} for i in range(2)])
    before = last_tx(db)
    v2 = [{**spec("order/total", "decimal", doc="What the customer paid for an order, tax included."),
           "unique": "identity"}, spec("order/channel", doc="Sales channel an order came through.")]
    (tmp_path / "v2").mkdir()
    with pytest.raises(TransactError):
        admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path / "v2", "test-orders", v2))])
    assert last_tx(db) == before


def test_no_login_outlives_an_install(tmp_path, store_name, db):
    admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path, "test-orders", ORDERS))])
    assert db.execute("select count(*) from actor_login where actor = %s", (actors(db)["test-orders"],)).fetchone() == (0,)
    logins = db.execute("select rolname from pg_roles where rolcanlogin and starts_with(rolname, %s)",
                        (store_name,)).fetchall()
    assert logins == []


def test_dependencies_install_first_and_must_be_given_or_installed(tmp_path, store_name, db):
    lines = packages.load(manifest(tmp_path, "test-lines", LINES, depends_on=["test-orders"]))
    with pytest.raises(PackageError, match="test-lines depends on test-orders, which is neither installed"):
        admin.install(ADMIN_DSN, store_name, [lines])
    assert packages.installed(db) == set()

    orders = packages.load(manifest(tmp_path, "test-orders", ORDERS))
    assert [r.package for r in admin.install(ADMIN_DSN, store_name, [lines, orders])] == ["test-orders", "test-lines"]
    # Once installed, a dependency need not be given again.
    (tmp_path / "more").mkdir()
    extra = manifest(tmp_path / "more", "test-returns", [spec("return/rma", doc="Returns authorisation number.")],
                     depends_on=["test-orders"])
    assert admin.install(ADMIN_DSN, store_name, [packages.load(extra)])[0].registered == ["return/rma"]


def test_dependency_cycles_are_refused(tmp_path):
    a = packages.load(manifest(tmp_path, "test-a", [spec("a/x")], depends_on=["test-b"]))
    b = packages.load(manifest(tmp_path, "test-b", [spec("b/y")], depends_on=["test-a"]))
    with pytest.raises(PackageError, match="depends on itself"):
        packages.install_order([a, b], set())


def test_a_conflicting_definition_in_the_store_refuses_the_package(tmp_path, store, store_name, db):
    store.register_attribute(spec("order/total", "string", doc="What the customer paid for an order, tax included."))
    before = last_tx(db)
    with pytest.raises(PackageError, match="order/total is decimal/one/none in the package but string/one/none"):
        admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path, "test-orders", ORDERS))])
    assert last_tx(db) == before


def test_a_near_match_already_in_the_store_refuses_the_package(tmp_path, store, store_name, db):
    store.register_attribute(spec("order/order_no", unique="identity", doc="Our number for a sales order."))
    with pytest.raises(RegistrationRefused) as refused:
        admin.install(ADMIN_DSN, store_name, [packages.load(manifest(tmp_path, "test-orders", ORDERS))])
    assert [m.ident for m in refused.value.near_matches["order/number"]] == ["order/order_no"]
    assert db.execute("select count(*) from attr where ident like 'order/%'").fetchone() == (1,)


def test_manifests_are_checked_before_anything_is_written(tmp_path):
    with pytest.raises(PackageError, match="no manifest.json"):
        packages.load(tmp_path)
    bad = manifest(tmp_path, "test-bad", [spec("x/a"), spec("x/a"), {"type": "string"}],
                   skills=["../elsewhere/SKILL.md", "missing.md"], licence="MIT")
    with pytest.raises(PackageError) as refused:
        packages.load(bad / "manifest.json")
    problems = "\n".join(refused.value.problems)
    for expected in ["unexpected keys ['licence']", "x/a appears twice", "attribute 2 has no ident",
                     "skill ../elsewhere/SKILL.md is not a file", "skill missing.md is not a file"]:
        assert expected in problems
    (tmp_path / "Bad_Name").mkdir()
    (tmp_path / "Bad_Name" / "manifest.json").write_text(json.dumps({"name": "Bad_Name", "version": "1",
                                                                     "doc": "x", "attributes": [spec("x/a")]}))
    with pytest.raises(PackageError, match="lowercase words joined by hyphens"):
        packages.load(tmp_path / "Bad_Name")


def test_the_cli_installs_and_reports(tmp_path, store_name, capsys):
    directory = str(manifest(tmp_path, "test-orders", ORDERS))
    assert cli.main(["--admin-dsn", ADMIN_DSN, "install", store_name, directory]) == 0
    assert "test-orders 0.1.0: registered 3 attributes in transaction" in capsys.readouterr().out
    assert cli.main(["--admin-dsn", ADMIN_DSN, "install", store_name, directory]) == 0
    assert capsys.readouterr().out == "test-orders 0.1.0: already installed\n"
    (tmp_path / "v2").mkdir()
    v2 = str(manifest(tmp_path / "v2", "test-orders", [{**ORDERS[1], "cardinality": "many"}, *ORDERS[::2],
                                                       spec("order/channel", doc="Sales channel an order came through.")]))
    assert cli.main(["--admin-dsn", ADMIN_DSN, "install", store_name, v2]) == 0
    assert re.fullmatch(r"test-orders 0.1.0: evolved order/placed_at in transaction \d+; registered 1 attributes in"
                        r" transaction \d+, 3 already registered\n", capsys.readouterr().out)
    lines = str(manifest(tmp_path, "test-lines", LINES, depends_on=["test-missing"]))
    assert cli.main(["--admin-dsn", ADMIN_DSN, "install", store_name, lines]) == 1
    assert "test-missing, which is neither installed" in capsys.readouterr().err
