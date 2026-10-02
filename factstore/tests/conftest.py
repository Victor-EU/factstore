import os
import secrets

import psycopg
import pytest

from factstore import admin, connect

ADMIN_DSN = os.environ.get("FACTSTORE_TEST_ADMIN_DSN", "postgresql://postgres:postgres@localhost:54329/postgres")


@pytest.fixture(scope="session", autouse=True)
def postgres():
    try:
        psycopg.connect(ADMIN_DSN, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.exit("no Postgres at FACTSTORE_TEST_ADMIN_DSN; start one with `docker compose up -d`", returncode=2)


@pytest.fixture
def store_name():
    """A bare store, without factstore-core: the kernel knows no names, so its tests don't either."""
    name = f"t_{secrets.token_hex(4)}"
    admin.init_store(ADMIN_DSN, name, core=False)
    yield name
    admin.drop_store(ADMIN_DSN, name)


@pytest.fixture
def writer(store_name):
    """A writer credential for a fresh actor."""
    return admin.create_actor(ADMIN_DSN, store_name, "test agent")


@pytest.fixture
def store(writer):
    with connect(writer.dsn) as s:
        yield s


@pytest.fixture
def exciser(store_name, writer):
    """The same actor's excision credential."""
    cred = admin.create_credential(ADMIN_DSN, store_name, writer.actor, excise=True)
    with connect(cred.dsn) as s:
        yield s


@pytest.fixture
def owner_conn(store_name):
    """The store as its owner role: may do anything Postgres privileges allow, so only triggers stop it."""
    with psycopg.connect(psycopg.conninfo.make_conninfo(ADMIN_DSN, dbname=store_name), autocommit=True) as conn:
        conn.execute(f"set role {admin.roles(store_name)[0]}")
        yield conn


def attr(ident, type_, cardinality="one", doc=None, **extra):
    return {"ident": ident, "type": type_, "cardinality": cardinality, "doc": doc or f"Test attribute {ident}.",
            **extra}
