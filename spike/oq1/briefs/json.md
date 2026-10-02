# Brief

You are answering questions about a company by querying its fact store. You have never seen this store. This brief is all you get: the documentation of the store's `query` tool (JSON patterns), the attributes in the store, and ten questions from the company's operations manager.

The company is Acme Hearth, a brand that has kitchen and home goods made in China and sells them in the US. Today is 1 October 2026.

## How to run a query

A command stands in for the `query` tool. The query goes on stdin; `--as-of` is the tool's `as_of` parameter:

```bash
cd /Users/victor/Factstore/spike/oq1 && /Users/victor/Factstore/factstore/.venv/bin/python run.py json --agent AGENT [--as-of VALUE] <<'EOF'
<your query>
EOF
```
Replace AGENT with the agent name you were given.

It prints the result as JSON, or an error.

## Your answers

Write them as JSON to `/Users/victor/Factstore/spike/oq1/answers/AGENT.json`:

```json
{"answers": [{"question": 1, "rows": [["value", "value"]], "query": "the final query you used", "as_of": null}]}
```

`rows` is the answer: one array per row, with values in the order the question's columns list them. Copy values exactly as the query results show them. A count or total is a single row.

---

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


---

# Attributes in this store

Every attribute: name, value type, cardinality, whether it is an identity (one entity per value), and its doc.

| attribute | type | cardinality | identity | doc |
|---|---|---|---|---|
| amazon/asin | string | one | yes | Amazon's catalogue ID for a product (ASIN). |
| amazon/fba_line | string | one | yes | One SKU in an FBA inbound shipment, as shipment ID / seller SKU. |
| amazon/fba_shipment_id | string | one | yes | Amazon's ID for an inbound shipment of our stock to FBA. |
| amazon/fnsku | string | one | yes | Amazon fulfilment network SKU on the label of our FBA stock. |
| amazon/order_id | string | one | yes | Amazon's ID for an order, e.g. 113-1234567-1234567. |
| amazon/order_line | string | one | yes | One item line of an Amazon order, as order ID / seller SKU. |
| amazon/seller_sku | string | one | yes | SKU we list a product under in Amazon Seller Central. |
| core/authoritative_source | string | one |  | System authoritative for an attribute, e.g. shopify; asserted on the attribute's own entity. |
| core/confidence | decimal | one |  | How sure the writer is of a transaction's facts, from 0 to 1. |
| core/currency | string | one |  | ISO 4217 code of the currency every amount on this entity is in. |
| core/evidence | ref | many |  | Document backing a transaction's facts, asserted on the transaction. |
| core/on_behalf_of | ref | one |  | Actor a transaction was written for, when the writer acts for someone else. |
| core/part_of | ref | many |  | The whole this entity is part of: a line's order, a shipment line's shipment. |
| core/period | date | one |  | First day of the accounting period an entity belongs to. |
| core/same_as | ref | one |  | The surviving entity this duplicate stands for; follow it when reading. |
| core/supersedes | ref | one |  | The earlier entity this one replaces in the world, e.g. a reissued invoice. |
| core/valid_from | date | one |  | First date on which this entity's facts hold in the world. |
| core/valid_to | date | one |  | Last date on which this entity's facts hold in the world. |
| customs/duty | decimal | one |  | Duties assessed on an entry, all tariff programmes together. |
| customs/entered_value | decimal | one |  | Value declared to customs on an entry, in the entry's currency. |
| customs/entry_no | string | one | yes | US customs entry number for an import, e.g. HB7-2604013-3. |
| customs/fees | decimal | one |  | Merchandise processing and harbor maintenance fees on an entry. |
| customs/filed_on | date | one |  | Date the broker filed a customs entry. |
| customs/shipment | ref | one |  | Shipment a customs entry clears. |
| document/hash | string | one | yes | SHA-256 of a document's bytes, in hex. |
| document/url | string | one |  | Where a document's bytes can be fetched. |
| factory/item_code | string | one | yes | A factory's own code for an item, prefixed with our supplier code because codes repeat across factories: NBBW:MT-2231. |
| fs/actor | ref | one |  | Who submitted a transaction. Stamped by the kernel from the credential. |
| fs/at | instant | one |  | When a transaction was committed. Stamped by the kernel. |
| fs/cardinality | string | one |  | Whether an entity holds one value of an attribute or many. May change from one to many only. |
| fs/distinct_from | ref | many |  | A near-match attribute the registrant saw and declared to mean something else. |
| fs/doc | string | one |  | One-line description of an attribute. What attribute search runs over. |
| fs/excised_attribute | ref | many |  | An attribute whose facts an excision removed; absent when all of them were. |
| fs/excised_entity | ref | one |  | The entity whose facts an excision removed. |
| fs/ident | string | one | yes | Namespaced name of an attribute, e.g. customer/email. |
| fs/name | string | one |  | Display name of an actor. |
| fs/replaced_by | ref | one |  | The attribute that replaces this deprecated one. |
| fs/type | string | one |  | Value type of an attribute: string, decimal, boolean, date, instant or ref. Never changes. |
| fs/unique | string | one |  | none, or identity: at most one entity holds each value, and lookups address entities by it. |
| inventory/counted_at | instant | one |  | When a stock position was last counted. |
| inventory/location | ref | one |  | Location a stock position is at. |
| inventory/position | string | one | yes | A SKU at a location, as SKU code @ location code. |
| inventory/quantity | decimal | one |  | Units at a stock position when last counted. |
| inventory/sku | ref | one |  | SKU a stock position counts. |
| line/sku | ref | one |  | SKU on a sales or transfer line. |
| location/code | string | one | yes | Our code for a place stock can be, e.g. 3PL-NJ. |
| location/kind | string | one |  | What a location is: factory, in_transit, 3pl or fba. |
| location/name | string | one |  | Readable name of a stock location. |
| order/customer | ref | one |  | Customer account that placed an order. |
| po/etd | date | one |  | Date the supplier's goods leave port: the latest promise until they sail, then the actual date. |
| po_line/key | string | one | yes | A purchase order line, as PO number and line number: PO-2026-0007/3. |
| po_line/quantity | decimal | one |  | Units ordered on a purchase order line. |
| po_line/sku | ref | one |  | SKU ordered on a purchase order line. |
| po_line/unit_price | decimal | one |  | Price per unit on a purchase order line, in the order's currency. |
| po/number | string | one | yes | Our purchase order number, e.g. PO-2026-0007. |
| po/pi_number | string | one |  | Supplier's proforma invoice number confirming a purchase order. |
| po/placed_on | date | one |  | Date we placed a purchase order. |
| po/status | string | one |  | Where a purchase order is: draft, sent, confirmed, in_production, ready, shipped, received. |
| po/supplier | ref | one |  | Supplier a purchase order is placed with. |
| qc/inspected_on | date | one |  | Date a pre-shipment inspection took place. |
| qc/inspector | string | one |  | Inspection agency that carried out an inspection. |
| qc/po | ref | one |  | Purchase order whose goods an inspection checked. |
| qc/report_no | string | one | yes | Inspection agency's report number for a pre-shipment inspection. |
| qc/result | string | one |  | Outcome of a pre-shipment inspection: PASS or FAIL. |
| qc/sample_size | decimal | one |  | Units the inspector pulled and checked, per the AQL table. |
| receipt/shipment | ref | one |  | Shipment a warehouse receipt booked in. |
| shipment/booking_no | string | one | yes | Forwarder's booking (SO) number for an ocean shipment. |
| shipment/container_no | string | one |  | ISO 6346 number of the container a shipment travels in; none for LCL. |
| shipment/delivered_at | instant | one |  | When a shipment was delivered to our warehouse. |
| shipment/destination | string | one |  | UN/LOCODE of a shipment's port of discharge. |
| shipment/eta | instant | one |  | When a shipment is expected at its port of discharge, latest estimate. |
| shipment/etd | instant | one |  | When a shipment leaves its port of loading: estimate, then actual. |
| shipment/freight_cost | decimal | one |  | Ocean freight charged for a shipment, in the shipment's currency. |
| shipment/hbl | string | one |  | House bill of lading number the forwarder issued. |
| shipment_line/cartons | decimal | one |  | Cartons of a purchase order line loaded in a shipment. |
| shipment_line/key | string | one | yes | A shipment line, as booking number and line number. |
| shipment_line/po_line | ref | one |  | Purchase order line whose goods a shipment line carries. |
| shipment_line/quantity | decimal | one |  | Units of a purchase order line loaded in a shipment. |
| shipment/mode | string | one |  | How a shipment travels: 40HQ, 20GP or LCL. |
| shipment/origin | string | one |  | UN/LOCODE of a shipment's port of loading. |
| shipment/status | string | one |  | Where a shipment is: booked, departed, arrived, delivered. |
| shipment/vessel | string | one |  | Vessel name and voyage a shipment sails on. |
| shopify/customer_id | string | one | yes | Shopify's ID for a customer account. |
| shopify/line_item_id | string | one | yes | Shopify's ID for one line of an order. |
| shopify/order_id | string | one | yes | Shopify's ID for an order. |
| shopify/variant_id | string | one | yes | Shopify's ID for a product variant. |
| sku/code | string | one | yes | Our SKU code for a sellable product variant, e.g. AH-KTL-0001-BLK. |
| sku/family | string | one |  | Three-letter code of the product family a SKU belongs to, e.g. KTL. |
| sku/hs_code | string | one |  | HTSUS tariff code a SKU is imported under. |
| sku/launched_on | date | one |  | Date a SKU first went on sale. |
| sku/retail_price | decimal | one |  | List price of a SKU to consumers, in the SKU's currency. |
| sku/supplier | ref | one |  | Supplier that makes a SKU. |
| sku/title | string | one |  | Product name and variant as we sell it. |
| sku/upc | string | one | yes | 12-digit UPC barcode printed on a SKU's packaging. |
| supplier/address | string | one |  | Postal address of a supplier's factory. |
| supplier/code | string | one | yes | Short code we use for a supplier, e.g. NBBW. |
| supplier/contact_name | string | one |  | Our main contact person at a supplier. |
| supplier/currency | string | one |  | Currency a supplier invoices in. |
| supplier/incoterm | string | one |  | Incoterm a supplier sells on, with the named place, e.g. FOB Ningbo. |
| supplier/name | string | one |  | Supplier's legal name as printed on its invoices. |
| supplier/name_cn | string | one |  | Supplier's registered Chinese name. |
| supplier/payment_terms | string | one |  | Payment terms agreed with a supplier, e.g. 30% deposit, 70% before shipment. |
| supplier/port | string | one |  | UN/LOCODE of the port a supplier ships from, e.g. CNNGB. |
| tpl/item_code | string | one | yes | The 3PL warehouse's code for one of our items. |
| tpl/receipt_no | string | one | yes | The 3PL's receipt number for goods it booked in. |


---

# Questions

1. What is in transit for SKU AH-KTL-0001-BLK? In transit means on a shipment whose status is departed or arrived. For each such shipment, give its booking number, status, ETA, and the total units of that SKU on it.
   Columns: booking number, status, ETA, units.
2. Which of supplier NBBW's purchase orders now have an ETD later than the ETD first recorded for them? Give the PO number, the first ETD recorded, and the current ETD.
   Columns: PO number, first ETD, current ETD.
3. As of transaction 103815, the last write before 1 July 2026: which shipments had status departed or arrived, and what was each one's ETA as recorded at that point? Give the booking number, status and ETA.
   Columns: booking number, status, ETA.
4. For customs entries filed from 1 April 2026 to 30 June 2026 inclusive, give the number of entries, the total entered value, the total duty and the total fees.
   Columns: entries, entered value, duty, fees.
5. For pre-shipment inspections carried out in 2026, how many were there per supplier and result? Give the supplier code, the result and the count.
   Columns: supplier code, result, count.
6. For the product with ASIN B0BVUGZ3AT, give our SKU code, its Shopify variant ID, FNSKU, Amazon seller SKU, 3PL item code and factory item code, and the code of the supplier that makes it.
   Columns: SKU code, Shopify variant ID, FNSKU, seller SKU, 3PL item code, factory item code, supplier code.
7. What is each supplier's open purchase order value? Open POs are those whose status is neither shipped nor received. Per supplier, give the supplier code, the currency, and the total of quantity times unit price over every line of its open POs.
   Columns: supplier code, currency, value.
8. How many Shopify orders has the person behind Shopify customer 8995877069469 placed, counting every account recorded as the same person? Duplicate accounts point at the account they duplicate with core/same_as, sometimes through several links. Give the number of accounts and the number of orders.
   Columns: accounts, orders.
9. Who recorded PO-2026-0023's current ETD, in which transaction, and when? Give the actor's name, the transaction ID and the time it was recorded.
   Columns: actor, transaction, time.
10. How many units of SKU AH-TWL-0007-NAT were last counted at each location whose kind is factory or in_transit? Give the location code, its kind and the quantity.
   Columns: location code, kind, quantity.
