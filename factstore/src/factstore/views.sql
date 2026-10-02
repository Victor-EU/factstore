-- The read side: every attribute is a view named after it, in three schemas.
--
--   current."po/status"(e, v, tx)      current state, from `cur`
--   asof."po/status"(e, v, tx)         state as of the transaction in setting factstore.as_of
--   history."po/status"(e, v, tx, op)  every fact in the log, up to factstore.as_of if set
--
-- query puts `current` or `asof` on the search path, so the same SQL reads either. Every view
-- is a plain select (the as-of fold is an anti-join), so Postgres flattens it into the query
-- and joins on e or v use the indexes on `cur` and `fact`.
--
-- Idempotent: init applies it after schema.sql, and upgrade applies it again to rebuild the
-- views of an existing store. Applied as the store's owner, with the same placeholders.

drop schema if exists current cascade;
drop schema if exists asof cascade;
drop schema if exists history cascade;
create schema current;
create schema asof;
create schema history;

create or replace function fs_as_of() returns bigint
language sql stable as $$ select nullif(current_setting('factstore.as_of', true), '')::bigint $$;

create or replace function fs_create_views(p_attr bigint) returns void
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_ident text;
  col text;
begin
  select ident, 'v_' || type into v_ident, col from attr where id = p_attr;
  execute format($v$
    create view current.%1$I as
      select e, %2$I as v, tx from public.cur where a = %3$s and %2$I is not null$v$, v_ident, col, p_attr);
  -- A value holds as of T if it was asserted by T and no later fact by T touches the same value.
  execute format($v$
    create view asof.%1$I as
      select f.e, f.%2$I as v, f.tx from public.fact f
      where f.a = %3$s and f.op and f.tx <= public.fs_as_of()
        and not exists (select 1 from public.fact g
                        where g.e = f.e and g.a = %3$s and g.%2$I = f.%2$I
                          and g.tx > f.tx and g.tx <= public.fs_as_of())$v$, v_ident, col, p_attr);
  execute format($v$
    create view history.%1$I as
      select e, %2$I as v, tx, case when op then 'assert' else 'retract' end as op from public.fact
      where a = %3$s and (public.fs_as_of() is null or tx <= public.fs_as_of())$v$, v_ident, col, p_attr);
  execute format('grant select on current.%1$I, asof.%1$I, history.%1$I to __WRITER__, __EXCISER__', v_ident);
end $$;

create or replace function fs_attr_views() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform fs_create_views(new.id);
  return new;
end $$;

drop trigger if exists attr_views on attr;
create trigger attr_views after insert on attr
  for each row execute function fs_attr_views();

select fs_create_views(id) from attr;

-- Everything about an entity at a glance: every value, as text, with its attribute's name.
create view current.facts as
  select c.e, a.ident as a,
         coalesce(c.v_string, c.v_decimal::text, c.v_boolean::text, c.v_date::text, c.v_instant::text,
                  c.v_ref::text) as v, c.tx
  from public.cur c join public.attr a on a.id = c.a;

create view asof.facts as
  select f.e, a.ident as a,
         coalesce(f.v_string, f.v_decimal::text, f.v_boolean::text, f.v_date::text, f.v_instant::text,
                  f.v_ref::text) as v, f.tx
  from public.fact f join public.attr a on a.id = f.a
  where f.op and f.tx <= public.fs_as_of()
    and not exists (select 1 from public.fact g
                    where g.e = f.e and g.a = f.a and g.tx > f.tx and g.tx <= public.fs_as_of()
                      and coalesce(g.v_string, g.v_decimal::text, g.v_boolean::text, g.v_date::text,
                                   g.v_instant::text, g.v_ref::text)
                        = coalesce(f.v_string, f.v_decimal::text, f.v_boolean::text, f.v_date::text,
                                   f.v_instant::text, f.v_ref::text));

grant usage on schema current, asof, history to __WRITER__, __EXCISER__;
grant select on current.facts, asof.facts to __WRITER__, __EXCISER__;
