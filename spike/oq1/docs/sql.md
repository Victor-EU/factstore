# Querying factstore with SQL

`query` runs one read-only SQL statement (PostgreSQL) over views of the store and returns the rows.

- `sql`: the statement.
- `as_of` (optional): a transaction ID, or an ISO 8601 instant with a timezone. The store is then read as it was after that transaction.

## The store as views

The store holds facts: an entity has a value for an attribute. Every attribute is a view named after it, such as `"po/status"`. Always double-quote the name, because it contains a slash.

| Column | Meaning |
|---|---|
| `e` | the entity, a bigint |
| `v` | the value, typed: `text`, `numeric`, `boolean`, `date`, `timestamptz`, or `bigint` (another entity's `e`) for refs |
| `tx` | the transaction that asserted this value |

There is one row per entity and value: at most one per entity for a `one` attribute, possibly several for a `many` attribute. An entity without a value has no row, so use `left join` for an attribute that may be absent. Join attributes of one entity on `e`: `from "po/number" n join "po/status" s using (e)`.

## Refs

A ref's `v` is the `e` of the entity it points to.
- Follow it forward: `join "supplier/code" sc on sc.e = ps.v`.
- Follow it backward by joining the other way. The lines of a PO are the rows of `"core/part_of"` whose `v` is the PO.
- Follow a ref through any number of hops with `with recursive`.

## Values

- Text compares as text.
- Decimals are exact `numeric`.
- Dates are written `'2026-04-01'`.
- Instants are written `'2026-04-01T00:00:00Z'`. They are returned in UTC.

## Transactions and history

Transactions are entities:
- `"fs/at"` holds when a transaction was committed.
- `"fs/actor"` is a ref to whoever wrote it, and the actor's name is in `"fs/name"`.

To find who recorded a value and when, join its `tx`: `join "fs/at" at on at.e = s.tx`. Transaction IDs increase in commit order.

The views show current state. Schema `history` has a view for every attribute, such as `history."po/etd"`, listing every fact ever recorded for that attribute, replaced values included. Its columns are `e`, `v`, `tx` and `op` (`'assert'` or `'retract'`). Replacing a value of a `one` attribute retracts the old value in the same transaction.

## As of

With `as_of`, every view, `history` included, shows the store as it was after that transaction. Do not filter on `tx` to reconstruct a past state; pass `as_of`.

## Everything about one entity

`facts(e, a, v, tx)` holds every current value, with the attribute name in `a` and the value as text: `select a, v from facts where e = 123`.

## Limits

Read-only, one statement, 10 s, 1000 rows.

## Examples

SKUs made by supplier HZTY, with their UPC:
```sql
select k.v as sku, u.v as upc
from "supplier/code" s
join "sku/supplier" ks on ks.v = s.e
join "sku/code" k on k.e = ks.e
left join "sku/upc" u on u.e = ks.e
where s.v = 'HZTY'
```

Units ordered per SKU on PO-2026-0003:
```sql
select k.v as sku, sum(q.v) as units
from "po/number" po
join "core/part_of" line on line.v = po.e
join "po_line/quantity" q on q.e = line.e
join "po_line/sku" ls on ls.e = line.e
join "sku/code" k on k.e = ls.v
where po.v = 'PO-2026-0003'
group by k.v
```

Every status shipment PBLNGB2605021 has had, when each was recorded, and by whom:
```sql
select h.v as status, h.op, at.v as recorded_at, name.v as actor
from "shipment/booking_no" b
join history."shipment/status" h on h.e = b.e
join "fs/at" at on at.e = h.tx
join "fs/actor" a on a.e = h.tx
join "fs/name" name on name.e = a.v
where b.v = 'PBLNGB2605021'
order by h.tx
```
