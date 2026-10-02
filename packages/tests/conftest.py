import os
import secrets
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from factstore import admin

ADMIN_DSN = os.environ.get("FACTSTORE_TEST_ADMIN_DSN", "postgresql://postgres:postgres@localhost:54329/postgres")
PACKAGES = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def postgres():
    try:
        psycopg.connect(ADMIN_DSN, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.exit("no Postgres at FACTSTORE_TEST_ADMIN_DSN; start one with `docker compose up -d`", returncode=2)


def new_store(*, core: bool = True) -> str:
    name = f"t_{secrets.token_hex(4)}"
    admin.init_store(ADMIN_DSN, name, core=core)
    return name


def owner(name: str) -> psycopg.Connection:
    return psycopg.connect(make_conninfo(ADMIN_DSN, dbname=name), autocommit=True)
