---
name: ecom-ops-ingest-documents
description: Read supplier and logistics documents into a factstore with the factstore-ecom-ops vocabulary, every fact backed by the document it came from. Covers proforma invoices, commercial invoices and packing lists, inspection reports, supplier chats such as WeChat exports, and forwarder, customs broker and warehouse emails. Use when asked to ingest, extract, read in or record supplier PDFs, chat exports or shipping emails, or purchase orders, shipments, inspections and customs entries.
---

# Ingest supplier and logistics documents

The supply side of the business lives in documents:
- a proforma invoice says what was ordered, and at what price;
- a commercial invoice and packing list say what shipped, in which container;
- an inspection report says whether the goods passed;
- chats and forwarder emails say when goods will sail or arrive;
- broker emails say what customs charged.

The store is primary for all of this. This skill turns the documents into facts in the factstore-ecom-ops vocabulary, each transaction pointing at the document it came from.

You need:
- the factstore MCP tools;
- factstore-core and factstore-ecom-ops installed;
- the catalogue run first, so SKUs carry their factory item codes and suppliers exist;
- a shell with Python, which helps with PDF text (`pypdf`) and with hashing files.

## Rules

1. **Every transaction carries its evidence.** Write no fact without it:
   ```json
   {"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", "<sha256 hex>"]}
   ```
2. **Every transaction says how sure you are, and different confidence means different transactions.**
   - A value printed in a document's table or labelled field: `core/confidence` "1".
   - A value you had to interpret, at the confidence you have, in its own transaction. Examples: a date written "3/8" or "3月8号", an item matched by its description, a PO named loosely ("PO 23", "the bamboo order").
3. **Address entities by their identifiers.** The kernel's lookups then make re-reading a document harmless.

   | Entity | Lookup |
   |---|---|
   | purchase order | `["po/number", "PO-2026-0007"]` |
   | PO line | `["po_line/key", "PO-2026-0007/3"]` |
   | shipment | `["shipment/hbl", …]` or `["shipment/booking_no", …]` |
   | shipment line | `["shipment_line/key", "<HBL>/<PO line key>"]` |
   | inspection | `["qc/report_no", …]` |
   | customs entry | `["customs/entry_no", …]` |
   | SKU, from a factory's item code | `["factory/item_code", "NBBW:MT-1574"]` |

4. **One shipment, several identifiers.** A booking confirmation knows the booking (SO) number. A pre-alert and a commercial invoice know the house bill (HBL) and the container. All three describe one shipment.
   - Before creating a shipment, look for it under every identifier the document gives.
   - If it isn't found, look for a booking on the same vessel and voyage carrying the same POs.
   - When you find it, add the new identifier to that entity. Don't create a second shipment.
5. **A changed value is a new assertion on the same attribute.** A slipped ETD or a revised ETA is never a new attribute. The store keeps the old value in history.
6. **Read in issue order.** A later document's value must land after an earlier one's, because the last assertion wins. When a document is older than the one behind a value already in the store, don't let it replace that value.
7. **Record what the vocabulary holds, and leave the rest in the document.** These are not facts:
   - totals that are sums of lines;
   - carton numbering, weights and volumes;
   - bank details and boilerplate;
   - small talk, stickers and photos;
   - the text of a message.

   If something matters and nothing in the vocabulary fits, don't register an attribute: list it in your report as a gap in the package.
8. **Skip what you have read.** A document has been read when the store holds the facts it gives, with the document as their evidence.
   - Its hash being in the store isn't enough. Another skill may have cited it for less: the catalogue reads invoices for a product's item code and HS code, but not for the shipment.
   - List what a document backs:
     ```sql
     select f.a, count(*) from facts f
     join "core/evidence" ev on ev.e = f.tx join "document/hash" h on h.e = ev.v
     where h.v = '<sha256>' group by 1
     ```
   - Read it again only if what it gives is missing, or if asked.
   - A document in the store without its issue date (below) gets one when you read it.

## Documents

Each document is an entity with three attributes:
- `document/hash`: the SHA-256 of its bytes, hex. This is its identity.
- `document/url`: where it is, as a URL or its path under the export folder (`supplier_docs/MT251009-01.pdf`).
- `document/issued_at`: when it was issued, as an instant.
  - A PDF: the date printed on it (the PI's date, the invoice date, the inspection date), as midnight where it was issued: `2025-10-09T00:00:00+08:00` in China.
  - A chat message: its timestamp, in the export's time zone.
  - An email: its `Date` header.

  The store's own time is when you write, and you are writing a year of history today. The issue date is how a reader asks what was known on a past date, so every document needs one.

A chat message and an email are each a document of their own:
- **Chat message.** Hash the message's lines exactly as exported (its header line with the time and sender, then its text), UTF-8, without the blank line after it. The url is `wechat/<file>#<n>`, where n counts messages from 1 within the file.
- **Email.** Hash the message's raw bytes as stored in the mailbox, from its `From ` line. The url is `mid:<Message-ID>`, without the angle brackets.

Create the document in the same transaction as the first facts from it. The lookup creates it:

```json
[{"e": ["document/hash", "9f2c…"], "a": "document/url", "v": "supplier_docs/MT251009-01.pdf"},
 {"e": ["document/hash", "9f2c…"], "a": "document/issued_at", "v": "2025-10-09T00:00:00+08:00"},
 {"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", "9f2c…"]},
 {"e": "tmp:tx", "a": "core/confidence", "v": "1"},
 {"e": ["po/number", "PO-2025-0143"], "a": "po/pi_number", "v": "MT251009-01"},
 {"e": ["po/number", "PO-2025-0143"], "a": "po/etd", "v": "2025-12-05"}]
```

## What each document gives

### Proforma invoice (PI)

The supplier confirms our PO. The PO is the one named "Your PO".

- **On the PO:**
  - `po/pi_number`;
  - `po/supplier`: the supplier entity, found by the legal name on the letterhead (`supplier/name`) or from its item codes;
  - `po/etd`: the delivery or ETD date;
  - `core/currency`, as ISO 4217 (RMB is CNY);
  - `po/status` "confirmed" (see PO status, below).
- **Each item row is a PO line.** If the PO already has lines, match rows to lines by SKU. Otherwise number them 1, 2, 3… in the PI's order, as `PO-…/1`. Each line gets:
  - `core/part_of`: the PO;
  - `po_line/sku`: the SKU, looked up by `factory/item_code` as `<supplier code>:<item no>`;
  - `po_line/quantity`;
  - `po_line/unit_price`.
- **On the supplier,** as printed: `supplier/name_cn`, `supplier/address`, `supplier/incoterm`, `supplier/payment_terms`. Also:
  - `supplier/name`: the English legal name, capitalised as in the bank details ("Shenzhen Hetai Electric Appliance Co., Ltd."), not the letterhead's capitals;
  - `supplier/currency`: the PI's currency;
  - `supplier/port`: the UN/LOCODE of the price term's port (FOB Yantian is CNYTN);
  - `supplier/contact_name`: the name the PI is signed with, only if the business has allowed this attribute for personal data. The store's instructions show how to check. Otherwise leave it out.

### Commercial invoice and packing list (CI/PL)

What left the factory, on which bill of lading. Find the shipment by the B/L number, `["shipment/hbl", …]`.

- **On the shipment:**
  - `shipment/container_no`, unless the shipment is LCL;
  - `shipment/vessel`: vessel and voyage, as printed;
  - `shipment/origin` and `shipment/destination`, as UN/LOCODEs.
- **Each invoice row is a shipment line,** keyed `<HBL>/<PO line key>`. Find the PO line from the order number and the row's item code. Each line gets:
  - `core/part_of`: the shipment;
  - `shipment_line/po_line`;
  - `shipment_line/quantity`: pieces, from the invoice;
  - `shipment_line/cartons`: from the packing list's row for the same item.
- **HS code on the SKU:** `sku/hs_code`, if the SKU has none. If the SKU's HS code differs, report it rather than overwriting it.

### Inspection report

Find the inspection by its report number. Record:
- `qc/po`;
- `qc/inspected_on`;
- `qc/result`: PASS or FAIL;
- `qc/inspector`: the agency's name in normal capitalisation;
- `qc/sample_size`.

Defect lists stay in the report.

### Supplier chat

Most messages carry no facts. These do:
- **A PO we sent** ("new PO PO-2026-0023 attached"): `po/placed_on`, the message's date in the export's time zone, and `po/supplier`, the supplier the chat is with.
- **A new ETD for a PO:** `po/etd`.
  - Suppliers often name the order by their own PI number ("YD-26-003 大货要晚一点"), not our PO number. Find the PO whose `po/pi_number` it is, which the proforma invoice recorded, and address it by its PO number.
  - Suppliers write dates in China time and without a year: "3/8" and "3月8号" are 8 March, in the next 8 March after the message.
  - The export's timestamps are in the exporter's time zone; the export header or the user tells you which.
  - These are interpreted values, so give them confidence below 1.
- **A container number for a shipment:** `shipment/container_no`, on the shipment of the PO the message names. Use confidence 0.9 if the PO is named loosely.
- **The supplier acknowledging our deposit, or saying production has started:** `po/status` "in_production" (see PO status). It belongs to the PO our deposit message names. If that message names none, it belongs to the PO whose deposit matches the amount: the PI's total times its deposit share. The reply names the PO only through the message it answers, so use confidence 0.9.

**Read each message with the ones before it.** A reply often names nothing: "Got it, thanks" or "已收到" after our deposit message acknowledges that deposit. A script's patterns cover only the phrasings you have seen, in the languages you saw them in. So after each message from us about a PO or a payment, read the supplier's replies yourself, up to our next message. Check each against what your script made of it.

Price changes, holiday closures, payment amounts and sample couriers have no attributes in the package. List them in your report. A supplier's acknowledgement of a payment still moves its PO's status.

### Forwarder email

- **Booking confirmation:** the shipment by `["shipment/booking_no", SO]`. Record:
  - `shipment/mode`: 40HQ, 20GP or LCL;
  - `shipment/vessel`;
  - `shipment/origin` and `shipment/destination`;
  - `shipment/etd` and `shipment/eta`;
  - `shipment/status` "booked".
- **Rolled booking:** new `shipment/etd` and `shipment/eta` on the same booking.
- **Pre-alert or shipping advice.** Find the shipment by HBL, or by the booking on the same vessel and voyage for the same POs, and add `shipment/hbl` to it. Record:
  - `shipment/container_no`;
  - `shipment/etd`: the actual departure;
  - `shipment/eta`;
  - `shipment/status` "departed";
  - one shipment line for each cargo row, as for a commercial invoice.
- **ETA update:** `shipment/eta`.
- **Arrival notice:** `shipment/status` "arrived", and `shipment/eta` set to the arrival date.

`shipment/etd` and `shipment/eta` are instants. A date given without a time means 00:00 at the port's local time: China +08:00, US East -05:00 (-04:00 in summer), US West -08:00 (-07:00 in summer).

### Warehouse email

Receipt complete: the shipment whose container number the email gives (for LCL, its HBL). Record:
- `shipment/status` "delivered";
- `shipment/delivered_at`: when receiving completed, which is the email's time unless the email says otherwise.

Counts received and damaged have no attributes in the package. List discrepancies in your report.

### Customs broker email

Entry summary: the entry by `["customs/entry_no", …]`. Record:
- `customs/shipment`: the shipment, by the HBL or container number given;
- `customs/filed_on`: the email's date;
- `customs/entered_value`;
- `customs/duty`: every tariff programme together (HTS, Section 301, additional duties);
- `customs/fees`: MPF plus HMF;
- `core/currency`.

### PO status

`po/status` only moves forward, through draft, sent, confirmed, in_production, ready, shipped and received. Assert a status only when it is further along than the PO's current one.

| Status | When |
|---|---|
| confirmed | A proforma invoice for the PO. |
| in_production | The supplier says production has started, or acknowledges the deposit. |
| ready | An inspection report for the PO passed. After a failed inspection and rework, this is the later report. |
| shipped | All the PO's goods have sailed: every booking carrying it has a pre-alert or a commercial invoice, or its shipment lines add up to every line's ordered quantity. |
| received | Every shipment carrying the PO has been delivered. |

When a PO becomes shipped, also set `po/etd` to the actual departure date, from the pre-alert. `po/etd` is the latest promise until the goods sail, and the actual date after.

## Working through a folder

1. Extract every document's text and date into your working directory, along with its hash and url.
2. Sort the documents by issue date.
3. Read a few of each kind and each supplier's layout in full before writing anything.
4. For a run of documents with one layout, a script may extract the fields, using the SDK (`import factstore`; `factstore.transact(facts)` with the store in `FACTSTORE_DSN`). Check its output against the documents you read by hand.
5. Read what doesn't fit the layout yourself.
6. Write each document's transactions, in date order.
7. When something can't be resolved, such as an item code with no SKU or a B/L matching no shipment, write the facts you are sure of and list the rest.

## Finish with a report

- Documents read, by kind, and any skipped as already read.
- Entities created and updated, by kind.
- Facts written at confidence below 1, and why.
- Anything unresolved, and gaps in the vocabulary.
