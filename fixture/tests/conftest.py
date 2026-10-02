import os
import secrets

import psycopg
import pytest

from factstore import admin, connect
from factstore_fixture.simulate import Simulation

ADMIN_DSN = os.environ.get("FACTSTORE_TEST_ADMIN_DSN", "postgresql://postgres:postgres@localhost:54329/postgres")


@pytest.fixture(scope="session")
def world():
    """One default simulation, run to the end, with everything it yielded."""
    sim = Simulation(7)
    items = list(sim.run())
    return sim, items


@pytest.fixture
def store():
    try:
        psycopg.connect(ADMIN_DSN, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("no Postgres at FACTSTORE_TEST_ADMIN_DSN; start one with `docker compose up -d`")
    name = f"t_{secrets.token_hex(4)}"
    admin.init_store(ADMIN_DSN, name)
    try:
        cred = admin.create_actor(ADMIN_DSN, name, "fixture test")
        with connect(cred.dsn) as s:
            yield s
    finally:
        admin.drop_store(ADMIN_DSN, name)
