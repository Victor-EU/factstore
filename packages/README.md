# Vocabulary packages

Build plan M3. A package is a namespaced attribute set, the packages it builds on, and its skills (design §8). Installing one registers its attributes. Nothing else.

| Package | Attributes | What |
|---|---|---|
| [`factstore-core`](core/manifest.json) | 13 | The Part II conventions: `core/part_of`, `core/supersedes`, `core/same_as`, `core/currency`, `core/evidence`, domain time, provenance, and `document/hash` and `document/url`. `factstore init` installs it. |
| [`factstore-ecom-ops`](ecom-ops/manifest.json) | 69 | The supply side of a brand that makes in China and sells online: suppliers, SKUs and their IDs in each system, purchase orders, inspections, shipments, customs entries, and stock by location. Depends on core. |

Both came from the fixture's draft vocabulary. The fixture now installs them and registers only the sales-side identifiers itself (below).

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
- `skills` lists skill files in the package's directory. Both lists are empty until M4.

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
  - A conflicting definition already in the store refuses the package.
  - Docs in the store are left as they are.
- **The kernel learns no names.** The installer is generic code in [`factstore/packages.py`](../factstore/src/factstore/packages.py) and `admin.install`.
  - The kernel's tests run on bare stores without core (`init_store(..., core=False)`), so a change to core can't break them.
  - The wheel bundles core so `init` can install it; a source checkout reads `packages/core`.

## Tests

```bash
factstore/.venv/bin/pytest packages/tests
```

They check the M3 exit:
- both packages install on an empty store, each in one transaction by its own actor;
- installing twice changes nothing;
- 15 near-duplicates an agent might register are refused, each naming the package attribute it duplicates.

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
- **Gap for M4.** The fixture's commercial invoices and packing lists carry fields the package has no attributes for, such as invoice totals, weights and volumes. The ingestion skill (M4) decides what they need, and the package's next version adds it.
