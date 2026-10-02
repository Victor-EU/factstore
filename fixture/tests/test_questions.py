"""Build plan M2 exit: the ten questions answered through query, against the default world,
checked against a naive fold over the log."""

import secrets
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
import pytest

from conftest import ADMIN_DSN
from factstore import admin, connect
from factstore_fixture.load import load
from factstore_fixture.questions import JULY_1_MARK, QUESTIONS, REFERENCE_SQL, World, answers
from factstore_fixture.simulate import Simulation


@pytest.fixture(scope="module")
def loaded():
    try:
        psycopg.connect(ADMIN_DSN, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("no Postgres at FACTSTORE_TEST_ADMIN_DSN; start one with `docker compose up -d`")
    name = f"t_{secrets.token_hex(4)}"
    admin.init_store(ADMIN_DSN, name)
    try:
        cred = admin.create_actor(ADMIN_DSN, name, "fixture loader")
        with connect(cred.dsn) as store:
            stats = load(store, Simulation(7), batch=1000, marks=[JULY_1_MARK])
            july_1 = stats.marks[JULY_1_MARK]
            yield store, july_1, answers(World(store.conn, july_1))
    finally:
        admin.drop_store(ADMIN_DSN, name)


def norm(v):
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, Decimal)) and not isinstance(v, bool):
        return str(Decimal(v).normalize())
    return v


def rows(rs):
    return Counter(tuple(norm(v) for v in r) for r in rs)


@pytest.mark.parametrize("qid", [q["id"] for q in QUESTIONS])
def test_reference_sql_answers_the_question(loaded, qid):
    store, july_1, expected = loaded
    sql, as_of = REFERENCE_SQL[qid]
    result = store.query(sql, as_of=july_1 if as_of == "july_1" else as_of)
    assert rows(result.rows) == rows(expected[qid])
    assert not result.truncated


def test_every_question_has_an_answer(loaded):
    _, _, expected = loaded
    assert all(expected[q["id"]] for q in QUESTIONS)
