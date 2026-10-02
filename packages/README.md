# Vocabulary packages

Build plan M3. A package is a namespaced attribute set, the packages it builds on, and its skills (design §8). Installing one registers its attributes. Nothing else.

| Package | Attributes | What |
|---|---|---|
| [`factstore-core`](core/manifest.json) | 13 | The Part II conventions: `core/part_of`, `core/supersedes`, `core/same_as`, `core/currency`, `core/evidence`, domain time, provenance, and `document/hash` and `document/url`. `factstore init` installs it. |
| [`factstore-ecom-ops`](ecom-ops/manifest.json) | 69 | The supply side of a brand that makes in China and sells online: suppliers, SKUs and their IDs in each system, purchase orders, inspections, shipments, customs entries, and stock by location. Depends on core. Its skill, [`ecom-ops-ingest-documents`](ecom-ops/ingest-documents/SKILL.md), reads supplier PDFs, chats and shipping emails into it. |
| [`factstore-skills`](../factstore-skills/manifest.json) | 3 | The catalogue and ontology skills, and `shape/` for the shapes the ontology skill records ([factstore-skills](../factstore-skills/README.md)). Depends on core. |

Core and ecom-ops came from the fixture's draft vocabulary. The fixture now installs them and registers only the sales-side identifiers itself (below).

## Format

A package is a directory holding `manifest.json`:

```json
{
  "name": "factstore-ecom-ops",
  "version": "0.1.0",
  "doc": "One line on what the vocabulary covers.",
  "depends_on": ["factstore-core"],
  "skills": [],
  "attributes": [
    {"ident": "po/number", "type": "string", "cardinality": "one", "unique": "identity", "doc": "Our purchase order number, e.g. PO-2026-0007."},
    {"ident": "po/pi_number", "type": "string", "cardinality": "one", "doc": "Supplier's proforma invoice number confirming a purchase order.", "distinct_from": ["po/number"]}
  ]
}
```

- Each attribute is a `register_attribute` spec, written one per line so a diff shows one attribute per change.
- Packages follow the agents' rule: where the kernel finds a near match in the package or in a package it depends on, the manifest names it in `distinct_from`.
- `skills` lists the package's skills, each a `SKILL.md` in its directory, with a `name` and a `description` in its frontmatter ([Agent Skills](https://agentskills.io)).

## Installing

```bash
export FACTSTORE_ADMIN_DSN=postgresql://postgres:postgres@localhost:54329/postgres
factstore init demo                       # installs factstore-core
factstore install demo packages/ecom-ops  # dependencies must be installed or given in the same call
```

- **One transaction per package, all or nothing.** The registration runs as an actor named after the package, so the log says which package registered what.
  - The actor writes through a login that exists only for the install, then is dropped.
  - A store "has" a package when an actor of that name has registered attributes. That is the dependency check, and it needs no record beyond the log.
  - A store whose attributes were registered some other way doesn't count as having the package, even if every attribute matches. Stores loaded before M3 are like this. Give the dependency in the same call (`factstore install STORE packages/core packages/ecom-ops`); it registers nothing.
- **Installing again writes nothing.** That holds when the store already has every attribute with the same type, cardinality and uniqueness: no transaction and no new actor.
  - A new version registers only what it adds, as the same actor.
  - It may also make the two changes the kernel allows to an attribute: cardinality from one to many, and uniqueness from none to identity. These go in a transaction of their own, before the registration. If the store's values collide under a new identity, nothing is written.
  - Any other difference from the store refuses the package.
  - Docs in the store are left as they are.
- **The kernel learns no names.** The installer is generic code in [`factstore/packages.py`](../factstore/src/factstore/packages.py) and `admin.install`.
  - The kernel's tests run on bare stores without core (`init_store(..., core=False)`), so a change to core can't break them.
  - The wheel bundles core so `init` can install it; a source checkout reads `packages/core`.

## Tests

```bash
factstore/.venv/bin/pytest packages/tests
```

They check the M3 exit:
- each package installs on an empty store in one transaction, by its own actor;
- installing twice changes nothing;
- 19 near-duplicates an agent might register are refused, each naming the package attribute it duplicates.

They also check that a store with ecom-ops 0.1.0 upgrades to 0.2.0, and that every skill has the frontmatter agents load it by.

## What the near-match check catches

To find out what the exit test should hold the kernel to, I tried 30 plausible attributes an agent might register instead of reusing one from these packages:

- **Refused, as they should be.** Variants of a name are refused:
  - `shipment/booking_number`, `shipment/container_number`;
  - `po/po_number`, `po/revised_etd`;
  - `supplier/supplier_code`, `shipment/eta_date`;
  - `amazon/asin_code`, `shopify/variant`;
  - `customs/duty_amount`, `core/source`.

  Some are refused against the wrong attribute, which still sends the agent to look. `sku/hts_code` and `sku/barcode` match `sku/code`, not `sku/hs_code` and `sku/upc`.
- **Accepted: synonyms and abbreviations.** Trigrams can't see these, as the build plan's risk table expects:
  - `po/purchase_order_no` instead of `po/number`;
  - `inventory/qty_on_hand` and `po_line/qty` instead of the `quantity` attributes;
  - `document/link` and `document/sha256` instead of `document/url` and `document/hash`;
  - `qc/outcome` instead of `qc/result`;
  - `factory/sku_code` instead of `factory/item_code`;
  - `core/doc` instead of `core/evidence`;
  - `line/order` instead of `core/part_of`.

  Search does better than refusal here. `search_attributes` on the agent's own words ranked the package attribute in the top five in every case tried except a bare `qty`. So an agent that searches first, as the tool descriptions tell it to, finds the attribute even where registration wouldn't stop it. The plan's response stands: tighten the catalogue skill's mapping step (M4), and measure in M5.
- **The core conventions needed their docs reworded.** An attribute with the same name in another namespace is a near match only when the docs also overlap. So `order/part_of` and `po/currency` were accepted beside `core/part_of` and `core/currency`, and those duplicates are the costly ones: queries follow `core/part_of`, and the money convention puts one `core/currency` on each entity.
  - The two docs now use the words agents use ("belongs to"; "such as an order's or a purchase order's").
  - Both duplicates are now refused, and search finds the core attribute for "line belongs to order" and "purchase order currency".
  - Nothing in ecom-ops or the fixture needed a new `distinct_from` as a result.
  - `order/currency`, documented as "Currency the customer paid in", is still accepted.

## Decisions

- **Composite identity (OQ4): the default.** A factory's code for an item is one identity attribute holding `"<supplier code>:<factory code>"` (`factory/item_code`, e.g. `NBBW:MT-2231`), because codes repeat across factories. HS code is a plain attribute, since many SKUs share one.
- **Sales-side identifiers stay out of ecom-ops.** The package has the per-source SKU IDs the crosswalk needs (Shopify variant, ASIN, FNSKU, Amazon seller SKU, 3PL item code), as the build plan says. Order, customer and receipt identifiers are left to the catalogue skill. In the fixture they are [`CATALOGUE`](../fixture/src/factstore_fixture/vocabulary.py): 11 attributes registered beyond the package (an M5 measure).
- **`supplier/currency` stays.** It is the currency a supplier invoices in, a fact about the supplier. `core/currency` is the currency of the amounts on an entity.
- **Ecom-ops 0.2.0, for the ingestion skill (M4).**
  - **`shipment/hbl` is an identity.** A shipment has two identifiers. The forwarder's booking (SO) number comes first. The house bill (HBL) arrives at departure, and it is the only one the supplier's commercial invoice, the pre-alert, the arrival notice and the customs entry carry. Both have to address the shipment.
  - **A shipment line is keyed by the HBL and the PO line it carries:** `PBLHB2600032/PO-2026-0023/1`. It used to be the booking number and a line number, which no document listing shipment lines carries. A shipment carries a PO line at most once, so the pair is unique.
- **Ecom-ops 0.2.1 and factstore-skills 0.1.1, from the slice (M5).** These change skill text only; no attribute changed. [evals/m5](../evals/m5/README.md) has the runs.
  - **Ingestion.** A document counts as read when it backs the facts it gives, not just when its hash is in the store. The catalogue cites commercial invoices for item codes, and the ingestion runs had skipped them as read. The skill also records a PO's placed date from our "new PO" chat message, and a supplier's legal name, currency and port from its proforma invoice.
  - **Catalogue.** Before a script writes a join key, it lists the values that don't look like IDs: blanks, lists and odd spellings. One run had written "PO-1 / PO-2" as one PO number.
  - **Catalogue, records without an ID.** A record with no ID of its own, such as a row of a warehouse's outbound file, is still indexed when it names other records, under a key built from the fields that make it unique. Two of four runs had skipped the outbound file.
  - **Catalogue duplicates.** A mailbox drops its dots only at providers that ignore them, such as Gmail. One run dropped them at every domain, which merged different people.
- **What the commercial invoices and packing lists carry beyond the package stays in the documents.** That covers invoice totals, weights, volumes, carton numbers and seal numbers: the skill records nothing the package has no attribute for, and reports the gap instead. Nothing in the ten questions needs them. Landed cost, the stretch goal, would allocate freight by volume; if it is built, the package gains a volume per shipment line.
