# Querying factstore with JSON patterns

`query` takes a JSON object that describes the entities to match and what to return.

- `query`: the object.
- `as_of` (optional): a transaction ID, or an ISO 8601 instant with a timezone. The store is then read as it was after that transaction.

```json
{"where": {"?po": {"po/status": "confirmed", "po/number": "?n"}},
 "select": ["?n"]}
```

## where

The store holds facts: an entity has a value for an attribute.

`where` maps `?variables` to entity patterns. A pattern is an object of attribute → value spec, and an entity matches if its current values satisfy every spec. A value spec is one of:

- **A constant:** `"confirmed"`, `12.5`, `true`, `"2026-04-01"`.
- **A `?variable`:** binds the value. The same variable anywhere else must be equal, which is how patterns join.
- **A nested pattern, for a ref:** `"po/supplier": {"supplier/code": "NBBW"}`. Add `"id": "?s"` to name the entity it points to.
- **An operator object:**
  - `{"in": [...]}`, `{"not_in": [...]}`
  - `{"eq" | "ne" | "gt" | "gte" | "lt" | "lte": x}`
  - `{"starts_with": "AH-"}`
  - `{"missing": true}`: the entity has no value
  - `{"value": "?v", "gte": 5}`: binds and constrains at once

Further keys in a pattern:
- **Reverse refs:** prefix an attribute with `^`. `"^core/part_of": {...}` matches the entities whose `core/part_of` points at this one.
- **Transitive refs:** suffix an attribute with `*` (zero or more hops) or `+` (one or more). `"core/supersedes+": "?older"`.
- **`"not": {pattern}`:** the entity must not match the pattern.

`where` can also be a list of patterns, each naming its entity with `"id"`. Use the list form to put two specs on one attribute or to describe one entity in several patterns.

A `many` attribute matches once per value. Dates compare with `"2026-04-01"`, and instants with `"2026-04-01T00:00:00Z"`. Decimals are exact.

## Computed values and filters

- `"let": {"?value": ["*", "?q", "?p"]}` computes with `+` `-` `*` `/`.
- `"filter": [[">", "?a", "?b"]]` compares variables, with `=` `!=` `<` `<=` `>` `>=` `in` `not_in`.

## select

`select` lists `?variables` and aggregates: `{"sum": "?x"}`, `count`, `count_distinct`, `min`, `max`, `avg`.
- Rows group by the selected variables.
- An aggregate runs over every match, as in SQL, so a value repeated across matches counts each time.
- Results without aggregates are distinct rows.
- `"order_by": ["?x", "-?y"]` and `"limit": 10` are optional.

## Transactions and history

Transactions are entities:
- `fs/at` holds when a transaction was committed.
- `fs/actor` is a ref to whoever wrote it, and the actor's name is in `fs/name`.

Transaction IDs increase in commit order.

- `{"value": "?v", "tx": "?tx"}` binds the transaction that asserted the current value.
- Add `"log": true` to match every fact ever recorded for that attribute, replaced values included, and `"op": "?op"` to bind `"assert"` or `"retract"`. Replacing a value of a `one` attribute retracts the old value in the same transaction.
- `value` and `tx` also take comparisons: `"tx": {"lt": "?t"}`.

## As of

With `as_of`, every pattern, `"log": true` included, sees the store as it was after that transaction. Do not filter on `tx` to reconstruct a past state; pass `as_of`.

## Limits

1000 rows. Values come back as JSON: decimals as strings, dates as `YYYY-MM-DD`, instants in UTC, refs as entity IDs.

## Examples

SKUs made by supplier HZTY, with their UPC:
```json
{"where": {"?k": {"sku/supplier": {"supplier/code": "HZTY"}, "sku/code": "?sku", "sku/upc": "?upc"}},
 "select": ["?sku", "?upc"]}
```

Units ordered per SKU on PO-2026-0003:
```json
{"where": {"?line": {"core/part_of": {"po/number": "PO-2026-0003"},
                     "po_line/quantity": "?q",
                     "po_line/sku": {"sku/code": "?sku"}}},
 "select": ["?sku", {"sum": "?q"}]}
```

Every status shipment PBLNGB2605021 has had, when each was recorded, and by whom:
```json
{"where": {"?s": {"shipment/booking_no": "PBLNGB2605021",
                  "shipment/status": {"value": "?status", "tx": "?tx", "op": "?op", "log": true}},
           "?tx": {"fs/at": "?at", "fs/actor": {"fs/name": "?actor"}}},
 "select": ["?status", "?op", "?at", "?actor"]}
```
