"""Creating and dropping stores, actors and credentials. Needs a superuser connection.

A store is one Postgres database. Its credentials are Postgres logins: the schema
stamps each transaction with the actor behind the session's login, so a credential
cannot write as anyone else.
"""

import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from . import fs, kernel, packages
from .kernel import Change
from .packages import InstallResult, Package, PackageError
from .store import connect

# Store names prefix role names, which Postgres caps at 63 characters.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True)
class Credential:
    actor: int
    dsn: str
    excise: bool


def roles(store: str) -> tuple[str, str, str]:
    """The store's owner, writer and exciser roles. Logins are members of writer or exciser."""
    return f"{store}_owner", f"{store}_writer", f"{store}_exciser"


def init_store(admin_dsn: str, store: str, *, core: bool = True) -> InstallResult | None:
    """Create the database, its roles, the kernel schema and the fs/ attributes, then install
    factstore-core unless `core` is false."""
    _check_name(store)
    owner, writer, exciser = roles(store)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        for role in (owner, writer, exciser):
            conn.execute(sql.SQL("create role {} nologin").format(sql.Identifier(role)))
        conn.execute(sql.SQL("create database {} owner {}").format(sql.Identifier(store), sql.Identifier(owner)))

    with _connect(admin_dsn, store) as conn, conn.transaction(), conn.cursor() as cur:
        db = sql.Identifier(store)
        cur.execute(sql.SQL("revoke connect on database {} from public").format(db))
        cur.execute(sql.SQL("grant connect on database {} to {}, {}").format(
            db, sql.Identifier(writer), sql.Identifier(exciser)))
        cur.execute(sql.SQL("set local role {}").format(sql.Identifier(owner)))
        cur.execute(_script("schema.sql", store))
        cur.execute(_script("views.sql", store))
        _bootstrap(cur)
    return install(admin_dsn, store, [packages.core()])[0] if core else None


def install(admin_dsn: str, store: str, pkgs: list[Package]) -> list[InstallResult]:
    """Install packages, each after those it depends on. A package registers the attributes the
    store lacks in one transaction, all or none, as an actor named after it. One the store already
    has registers nothing and creates no actor."""
    _check_name(store)
    with _connect(admin_dsn, store) as conn:
        order = packages.install_order(pkgs, packages.installed(conn))
    return [_install(admin_dsn, store, p) for p in order]


def _install(admin_dsn: str, store: str, package: Package) -> InstallResult:
    with _connect(admin_dsn, store) as conn:
        have = {row[0]: row[1:] for row in conn.execute("select ident, type, cardinality, uniq from attr")}
    problems = []
    for spec in package.attributes:
        old = have.get(spec["ident"])
        new = (spec.get("type"), spec.get("cardinality"), spec.get("unique", "none"))
        if old is not None and old != new:
            problems.append(f"{package.name}: {spec['ident']} is {'/'.join(map(str, new))} in the package"
                            f" but {'/'.join(old)} in the store")
    if problems:
        raise PackageError(problems)
    if all(spec["ident"] in have for spec in package.attributes):
        return InstallResult(package.name, package.version, None, [], [s["ident"] for s in package.attributes])
    with _login_as(admin_dsn, store, package.name) as cred, connect(cred.dsn) as s:
        result = s.register_attribute(list(package.attributes))
    return InstallResult(package.name, package.version, result.tx, result.registered, result.existing)


@contextmanager
def _login_as(admin_dsn: str, store: str, name: str):
    """A credential, for the length of the block, for the actor called `name`; created if absent."""
    with _connect(admin_dsn, store) as conn, conn.transaction(), conn.cursor() as cur:
        kernel.lock(cur)
        cur.execute("select min(e) from cur where a = %s and v_string = %s", (fs.NAME, name))
        actor = cur.fetchone()[0] or _new_actor(cur, name)
        cred = _add_login(cur, admin_dsn, store, actor, False)
    try:
        yield cred
    finally:
        role = conninfo_to_dict(cred.dsn)["user"]
        with _connect(admin_dsn, store) as conn:
            conn.execute("delete from actor_login where rolname = %s", (role,))
            conn.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))


def upgrade_views(admin_dsn: str, store: str) -> None:
    """Rebuild the read-side views of an existing store from this version's views.sql."""
    _check_name(store)
    with _connect(admin_dsn, store) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute(sql.SQL("set local role {}").format(sql.Identifier(roles(store)[0])))
        cur.execute(_script("views.sql", store))


def _script(name: str, store: str) -> str:
    owner, writer, exciser = roles(store)
    text = resources.files("factstore").joinpath(name).read_text()
    for placeholder, value in (("__OWNER__", owner), ("__WRITER__", writer), ("__EXCISER__", exciser),
                               ("__LOCK__", str(fs.WRITER_LOCK))):
        text = text.replace(placeholder, value)
    return text


def create_actor(admin_dsn: str, store: str, name: str, *, excise: bool = False) -> Credential:
    """Create an actor named `name` and a credential for it."""
    with _connect(admin_dsn, store) as conn, conn.transaction(), conn.cursor() as cur:
        kernel.lock(cur)
        return _add_login(cur, admin_dsn, store, _new_actor(cur, name), excise)


def create_credential(admin_dsn: str, store: str, actor: int, *, excise: bool = False) -> Credential:
    """Another credential for an existing actor. Excision always needs its own."""
    with _connect(admin_dsn, store) as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("select 1 from cur where e = %s and a = %s", (actor, fs.NAME))
        if cur.fetchone() is None:
            raise ValueError(f"entity {actor} is not an actor")
        return _add_login(cur, admin_dsn, store, actor, excise)


def drop_store(admin_dsn: str, store: str) -> None:
    """Drop the database and every role belonging to the store. Irreversible."""
    _check_name(store)
    owner, writer, exciser = roles(store)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        logins = [row[0] for row in conn.execute(
            "select m.rolname from pg_auth_members am"
            " join pg_roles m on m.oid = am.member join pg_roles g on g.oid = am.roleid"
            " where g.rolname in (%s, %s)", (writer, exciser))]
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(store)))
        for role in [*logins, writer, exciser, owner]:
            conn.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(role)))


def _bootstrap(cur) -> None:
    """Register the fs/ attributes as facts about themselves, in the store's first transaction.
    The admin login acts as the admin actor."""
    cur.execute("insert into actor_login (rolname, actor) values (session_user, %s)", (fs.ADMIN_ACTOR,))
    cur.executemany(
        "insert into attr (id, ident, type, cardinality, uniq, doc) values (%s, %s, %s, %s, %s, %s)",
        [(d.id, d.ident, d.type, d.cardinality, d.unique, d.doc) for d in fs.ATTRIBUTES],
    )
    kernel.lock(cur)
    schema = kernel.load_schema(cur)
    tx = kernel.begin_tx(cur)
    changes = []
    for d in fs.ATTRIBUTES:
        changes += [Change(d.id, schema.fs(fs.IDENT), d.ident, True),
                    Change(d.id, schema.fs(fs.TYPE), d.type, True),
                    Change(d.id, schema.fs(fs.CARDINALITY), d.cardinality, True),
                    Change(d.id, schema.fs(fs.UNIQUE), d.unique, True),
                    Change(d.id, schema.fs(fs.DOC), d.doc, True)]
    changes.append(Change(fs.ADMIN_ACTOR, schema.fs(fs.NAME), "admin", True))
    kernel.write(cur, tx, changes)


def _new_actor(cur, name: str) -> int:
    schema = kernel.load_schema(cur)
    actor = kernel.allocate(cur, 1)[0]
    tx = kernel.begin_tx(cur)
    kernel.write(cur, tx, [Change(actor, schema.fs(fs.NAME), name, True)])
    return actor


def _add_login(cur, admin_dsn: str, store: str, actor: int, excise: bool) -> Credential:
    _, writer, exciser = roles(store)
    role = f"{store}_{'x' if excise else 'w'}{actor}_{secrets.token_hex(3)}"
    password = secrets.token_urlsafe(24)
    cur.execute(sql.SQL("create role {} login password {} in role {}").format(
        sql.Identifier(role), sql.Literal(password), sql.Identifier(exciser if excise else writer)))
    cur.execute("insert into actor_login (rolname, actor) values (%s, %s)", (role, actor))
    dsn = make_conninfo(admin_dsn, dbname=store, user=role, password=password)
    return Credential(actor, dsn, excise)


def _connect(admin_dsn: str, store: str) -> psycopg.Connection:
    return psycopg.connect(make_conninfo(admin_dsn, dbname=store), autocommit=True)


def _check_name(store: str) -> None:
    if not NAME_RE.match(store):
        raise ValueError(f"store names are lowercase letters, digits and underscores, at most 40: {store!r}")
