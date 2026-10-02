# Querying factstore with Datalog

`query` runs a Datalog query in Datomic's syntax, written as EDN text, and returns the rows.

- `query`: the query, `[:find ... :where ...]`.
- `rules` (optional): a vector of rules the query calls.
- `as_of` (optional): a transaction ID, or an ISO 8601 instant with a timezone. The store is then read as it was after that transaction.

## Data patterns

The store holds facts: an entity has a value for an attribute. Attributes are keywords, such as `:po/status`.

- `[?e :po/status ?s]` matches every entity `?e` that has a current value `?s`.
- A constant filters: `[?e :po/status "confirmed"]`.
- `_` matches anything.
- `[?e :po/status ?s ?tx]` also binds `?tx`, the transaction that asserted the value.

A variable used in several clauses joins them. A `many` attribute matches once per value.

## Refs

A ref's value is the entity it points to: `[?po :po/supplier ?s] [?s :supplier/code ?code]`.
- To go backward, write the same clause with the other side bound: `[?line :core/part_of ?po]` finds the parts of `?po`.
- To follow a ref through any number of hops, use a rule (below).

## Predicates and functions

- Comparisons: `[(< ?d "2026-04-01")]` with `<` `<=` `>` `>=` `=` `not=`.
- Membership: `[(contains? #{"a" "b"} ?x)]`.
- Arithmetic: `[(* ?q ?p) ?value]` with `+` `-` `*` `/`.
- Missing values: `[(missing? $ ?e :po/etd)]` and `[(get-else $ ?e :po/etd "none") ?etd]`.

Dates compare with strings like `"2026-04-01"`, and instants with `#inst "2026-04-01T00:00:00Z"`. Decimals are exact.

`(not ...)`, `(not-join [?vars] ...)`, `(or ...)`, `(or-join [?vars] ...)` and `(and ...)` work as in Datomic.

## Find and aggregates

`:find ?a ?b (count ?x) (sum ?y)`. The aggregates are `count`, `count-distinct`, `sum`, `min`, `max` and `avg`. They group by the other find variables.

As in Datomic, results are sets. An aggregate runs over the distinct combinations of the find variables, so repeated values collapse. Add `:with ?line` to keep one row per `?line`.

`(pull ?e [:sku/code {:sku/supplier [:supplier/code]}])` in `:find` returns an entity as a map.

## Rules

Rules name a set of clauses and may call themselves. Pass them in `rules`, and declare `:in $ %` in the query:
```clojure
[[(earlier ?doc ?old) [?doc :core/supersedes ?old]]
 [(earlier ?doc ?old) [?doc :core/supersedes ?mid] (earlier ?mid ?old)]]
```
Then `(earlier ?doc ?old)` in `:where` matches every document `?doc` replaced, directly or not.

## Transactions and history

Transactions are entities:
- `:fs/at` holds when a transaction was committed.
- `:fs/actor` is a ref to whoever wrote it, and the actor's name is in `:fs/name`.

Transaction IDs increase in commit order.

A five-element pattern `[?e :po/etd ?v ?tx ?added]` reads the whole log: every value ever asserted (`?added` true) or retracted (false), replaced values included. Replacing a value of a `one` attribute retracts the old value in the same transaction.

## As of

With `as_of`, every pattern, the five-element ones included, sees the store as it was after that transaction. Do not filter on `?tx` to reconstruct a past state; pass `as_of`.

## Limits

1000 rows. Values come back as JSON: decimals as strings, dates as `YYYY-MM-DD`, instants in UTC, refs as entity IDs.

## Examples

SKUs made by supplier HZTY, with their UPC:
```clojure
[:find ?sku ?upc
 :where [?s :supplier/code "HZTY"]
        [?k :sku/supplier ?s]
        [?k :sku/code ?sku]
        [(get-else $ ?k :sku/upc "") ?upc]]
```

Units ordered per SKU on PO-2026-0003:
```clojure
[:find ?sku (sum ?q)
 :with ?line
 :where [?po :po/number "PO-2026-0003"]
        [?line :core/part_of ?po]
        [?line :po_line/quantity ?q]
        [?line :po_line/sku ?k]
        [?k :sku/code ?sku]]
```

Every status shipment PBLNGB2605021 has had, when each was recorded, and by whom:
```clojure
[:find ?status ?added ?at ?actor
 :where [?s :shipment/booking_no "PBLNGB2605021"]
        [?s :shipment/status ?status ?tx ?added]
        [?tx :fs/at ?at]
        [?tx :fs/actor ?a]
        [?a :fs/name ?actor]]
```
