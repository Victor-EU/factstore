"""Candidate C: SQL over views. One view per attribute, named by the attribute, in schema `q`
(current state) and schema `history` (every fact in the log). Both honour the as-of setting.

Run once against the spike store, as the superuser. Creates a login `<store>_reader` that can
read the views and nothing else.
"""

import json
import sys
from pathlib import Path

import psycopg
from psycopg import sql

COLUMN = {"string": "v_string", "decimal": "v_decimal", "boolean": "v_boolean", "date": "v_date",
          "instant": "v_instant", "ref": "v_ref"}

FUNCTIONS = """
create or replace function public.fs_as_of() returns bigint language sql stable as
$$ select nullif(current_setting('factstore.as_of', true), '')::bigint $$;
"""


def views(attr_id: int, ident: str, type_: str) -> list[sql.Composed]:
    col = sql.Identifier(COLUMN[type_])
    name = sql.Identifier(ident)
    current = sql.SQL("""
create view q.{name} as
  select e, {col} as v, tx from public.cur where a = {a} and {col} is not null and public.fs_as_of() is null
  union all
  select e, v, tx from (
    select distinct on (e, {col}) e, {col} as v, tx, op from public.fact
    where a = {a} and tx <= public.fs_as_of() order by e, {col}, tx desc) s
  where op""").format(name=name, col=col, a=sql.Literal(attr_id))
    history = sql.SQL("""
create view history.{name} as
  select e, {col} as v, tx, case when op then 'assert' else 'retract' end as op from public.fact
  where a = {a} and (public.fs_as_of() is null or tx <= public.fs_as_of())""").format(
        name=name, col=col, a=sql.Literal(attr_id))
    return [current, history]


def install(admin_dsn: str, store: str) -> str:
    reader = f"{store}_reader"
    owner = f"{store}_owner"
    with psycopg.connect(admin_dsn, dbname=store, autocommit=True) as conn:
        conn.execute(sql.SQL("drop schema if exists q cascade"))
        conn.execute(sql.SQL("drop schema if exists history cascade"))
        if conn.execute("select 1 from pg_roles where rolname = %s", (reader,)).fetchone() is None:
            conn.execute(sql.SQL("create role {} login password 'reader'").format(sql.Identifier(reader)))
        with conn.transaction():
            conn.execute(sql.SQL("set local role {}").format(sql.Identifier(owner)))
            conn.execute(FUNCTIONS)
            conn.execute("create schema q")
            conn.execute("create schema history")
            for attr_id, ident, type_ in conn.execute("select id, ident, type from attr order by id").fetchall():
                for statement in views(attr_id, ident, type_):
                    conn.execute(statement)
            conn.execute("""
create view q.facts as
  select c.e, a.ident as a,
         coalesce(c.v_string, c.v_decimal::text, c.v_boolean::text, c.v_date::text, c.v_instant::text,
                  c.v_ref::text) as v, c.tx
  from public.cur c join public.attr a on a.id = c.a where public.fs_as_of() is null""")
            r = sql.Identifier(reader)
            conn.execute(sql.SQL("grant usage on schema q, history to {}").format(r))
            conn.execute(sql.SQL("grant select on all tables in schema q, history to {}").format(r))
        conn.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(store), sql.Identifier(reader)))
        conn.execute(sql.SQL("alter role {} set search_path = q").format(sql.Identifier(reader)))
        conn.execute(sql.SQL("alter role {} set default_transaction_read_only = on").format(sql.Identifier(reader)))
        conn.execute(sql.SQL("alter role {} set statement_timeout = '10s'").format(sql.Identifier(reader)))
    return f"host=localhost port=54329 dbname={store} user={reader} password=reader"


if __name__ == "__main__":
    store = sys.argv[1] if len(sys.argv) > 1 else "fs_spike"
    dsn = install("postgresql://postgres:postgres@localhost:54329/postgres", store)
    path = Path(__file__).with_name("store.json")
    config = json.loads(path.read_text())
    config["sql_reader_dsn"] = dsn
    path.write_text(json.dumps(config, indent=2))
    print(dsn)
