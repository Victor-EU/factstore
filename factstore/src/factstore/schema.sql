-- factstore kernel schema.
--
-- Applied by init as the store's owner role. __OWNER__, __WRITER__, __EXCISER__
-- and __LOCK__ are substituted first: roles are cluster-wide in Postgres, so each
-- store's roles carry its name.
--
-- `fact` is the log and the source of truth. Postgres keeps it append-only:
-- writers hold INSERT and SELECT on it, and triggers refuse UPDATE, TRUNCATE,
-- and any DELETE outside fs_excise(). `attr`, `cur` and `ident` are derived
-- from the log and maintained by the kernel in the same database transaction.
--
-- Fixed attribute IDs used below (see fs.py): 8 fs/actor, 9 fs/at,
-- 11 fs/excised_entity, 12 fs/excised_attribute.

create extension if not exists pg_trgm;

create sequence entity_seq start 1000;

-- Registered attributes: the schema facts, read back as a table.
create table attr (
  id          bigint primary key,
  ident       text not null unique,
  type        text not null check (type in ('string', 'decimal', 'boolean', 'date', 'instant', 'ref')),
  cardinality text not null check (cardinality in ('one', 'many')),
  uniq        text not null check (uniq in ('none', 'identity')),
  doc         text not null check (doc <> ''),
  replaced_by bigint references attr (id)
);

-- Which actor each login role acts as.
create table actor_login (
  rolname text primary key,
  actor   bigint not null
);

create table tx (
  id    bigint primary key,
  actor bigint not null,
  at    timestamptz not null
);
create index tx_at on tx (at);

create table fact (
  e         bigint not null,
  a         bigint not null references attr (id),
  v_string  text,
  v_decimal numeric,
  v_boolean boolean,
  v_date    date,
  v_instant timestamptz,
  v_ref     bigint,
  tx        bigint not null references tx (id),
  op        boolean not null, -- true: assert, false: retract
  check (num_nonnulls(v_string, v_decimal, v_boolean, v_date, v_instant, v_ref) = 1)
);
-- By entity, by attribute, by value (refs here; other values on `cur`), by transaction.
create index fact_eavt on fact (e, a, tx);
create index fact_aevt on fact (a, e, tx);
create index fact_vaet on fact (v_ref, a, e) where v_ref is not null;
create index fact_tx on fact (tx);

-- Current state: every (entity, attribute, value) asserted and not since retracted.
create table cur (
  e         bigint not null,
  a         bigint not null references attr (id),
  v_string  text,
  v_decimal numeric,
  v_boolean boolean,
  v_date    date,
  v_instant timestamptz,
  v_ref     bigint,
  tx        bigint not null,
  check (num_nonnulls(v_string, v_decimal, v_boolean, v_date, v_instant, v_ref) = 1)
);
create index cur_ea on cur (e, a);
create index cur_avet_string on cur (a, left(v_string, 200)) where v_string is not null;
create index cur_avet_decimal on cur (a, v_decimal) where v_decimal is not null;
create index cur_avet_date on cur (a, v_date) where v_date is not null;
create index cur_avet_instant on cur (a, v_instant) where v_instant is not null;
create index cur_vaet on cur (v_ref, a) where v_ref is not null;

-- Current values of identity attributes, by canonical key: the uniqueness backstop
-- and the index lookups resolve through.
create table ident (
  a   bigint not null references attr (id),
  key text not null check (length(key) <= 512),
  e   bigint not null,
  primary key (a, key)
);
create index ident_e on ident (e);

-- The actor behind the session's login. session_user, not current_user: SET ROLE cannot change it.
create function fs_current_actor() returns bigint
language plpgsql stable security definer set search_path = public, pg_temp as $$
declare
  v_actor bigint;
begin
  select actor into v_actor from actor_login where rolname = session_user;
  if v_actor is null then
    raise exception 'login % is not a factstore actor', session_user;
  end if;
  return v_actor;
end $$;

-- Stamp actor and commit order on every transaction, whatever the client sent.
create function fs_tx_stamp() returns trigger
language plpgsql set search_path = public, pg_temp as $$
begin
  perform pg_advisory_xact_lock(__LOCK__);
  if exists (select 1 from tx where id >= new.id) then
    raise exception 'transaction % is not after the latest transaction', new.id;
  end if;
  new.actor := fs_current_actor();
  new.at := greatest(clock_timestamp(),
                     coalesce((select max(at) from tx), '-infinity') + interval '1 microsecond');
  return new;
end $$;

create trigger tx_stamp before insert on tx
  for each row execute function fs_tx_stamp();

-- Record the stamps as facts about the transaction entity. Security definer, so
-- fact_guard can tell these inserts from a client's.
create function fs_tx_facts() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  insert into fact (e, a, v_ref, tx, op) values (new.id, 8, new.actor, new.id, true);
  insert into fact (e, a, v_instant, tx, op) values (new.id, 9, new.at, new.id, true);
  insert into cur (e, a, v_ref, tx) values (new.id, 8, new.actor, new.id);
  insert into cur (e, a, v_instant, tx) values (new.id, 9, new.at, new.id);
  return null;
end $$;

create trigger tx_facts after insert on tx
  for each row execute function fs_tx_facts();

-- Every fact names a registered attribute (foreign key) and carries a value of its type.
create function fs_fact_guard() returns trigger
language plpgsql set search_path = public, pg_temp as $$
declare
  v_type text;
  v_ok boolean;
begin
  if new.a in (8, 9, 11, 12) and current_user <> '__OWNER__' then
    raise exception 'fs/actor, fs/at and fs/excised_* are written by the kernel only';
  end if;
  select type into v_type from attr where id = new.a;
  v_ok := case v_type
            when 'string' then new.v_string is not null
            when 'decimal' then new.v_decimal is not null
            when 'boolean' then new.v_boolean is not null
            when 'date' then new.v_date is not null
            when 'instant' then new.v_instant is not null
            when 'ref' then new.v_ref is not null
            else false
          end;
  if not v_ok then
    raise exception 'value for attribute % is not of type %', new.a, v_type;
  end if;
  return new;
end $$;

create trigger fact_guard before insert on fact
  for each row execute function fs_fact_guard();

create function fs_fact_immutable() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' and current_setting('factstore.excising', true) = 'on' then
    return old;
  end if;
  raise exception 'facts are immutable: % is refused (only fs_excise removes facts)', tg_op;
end $$;

create trigger fact_no_update before update or delete on fact
  for each row execute function fs_fact_immutable();
create trigger fact_no_truncate before truncate on fact
  for each statement execute function fs_fact_immutable();

-- Attributes change in one direction only.
create function fs_attr_guard() returns trigger
language plpgsql as $$
begin
  if new.ident <> old.ident then
    raise exception 'attribute % cannot be renamed; deprecate it with fs/replaced_by', old.ident;
  end if;
  if new.type <> old.type then
    raise exception 'the type of % never changes', old.ident;
  end if;
  if old.cardinality = 'many' and new.cardinality = 'one' then
    raise exception 'cardinality of % may change from one to many only', old.ident;
  end if;
  if old.uniq = 'identity' and new.uniq = 'none' then
    raise exception 'uniqueness of % cannot be removed', old.ident;
  end if;
  return new;
end $$;

create trigger attr_guard before update on attr
  for each row execute function fs_attr_guard();

-- Physically remove facts about one entity, optionally only some attributes, and
-- record the excision: who, when, which entity and attributes, never the values.
create function fs_excise(p_entity bigint, p_attrs bigint[] default null) returns bigint
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_tx bigint;
  v_count bigint;
begin
  perform pg_advisory_xact_lock(__LOCK__);
  if exists (select 1 from attr where id = p_entity) then
    raise exception 'entity % is an attribute; deprecate it with fs/replaced_by instead', p_entity;
  end if;
  if exists (select 1 from tx where id = p_entity) then
    raise exception 'entity % is a transaction and cannot be excised', p_entity;
  end if;

  perform set_config('factstore.excising', 'on', true);
  delete from fact where e = p_entity and (p_attrs is null or a = any (p_attrs));
  get diagnostics v_count = row_count;
  perform set_config('factstore.excising', 'off', true);
  if v_count = 0 then
    raise exception 'entity % has no facts to excise', p_entity;
  end if;
  delete from cur where e = p_entity and (p_attrs is null or a = any (p_attrs));
  delete from ident where e = p_entity and (p_attrs is null or a = any (p_attrs));

  v_tx := nextval('entity_seq');
  insert into tx (id) values (v_tx);
  insert into fact (e, a, v_ref, tx, op) values (v_tx, 11, p_entity, v_tx, true);
  insert into cur (e, a, v_ref, tx) values (v_tx, 11, p_entity, v_tx);
  insert into fact (e, a, v_ref, tx, op) select v_tx, 12, x, v_tx, true from unnest(p_attrs) x;
  insert into cur (e, a, v_ref, tx) select v_tx, 12, x, v_tx from unnest(p_attrs) x;
  return v_tx;
end $$;

revoke all on all tables in schema public from public;
revoke all on function fs_excise(bigint, bigint[]) from public;

grant select on all tables in schema public to __WRITER__, __EXCISER__;
grant insert on tx, fact to __WRITER__;
grant insert, update on attr to __WRITER__;
grant insert, delete on cur, ident to __WRITER__;
grant usage on sequence entity_seq to __WRITER__;
grant execute on function fs_excise(bigint, bigint[]) to __EXCISER__;
