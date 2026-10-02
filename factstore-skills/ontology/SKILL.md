---
name: factstore-ontology
description: Describe the kinds of thing a factstore holds, such as Purchase order or Shipment, by reading attribute co-occurrence and refs from the stats tool. Propose names to a person, and record the names they confirm as shapes. Use when asked what the store contains, to describe or name its entity types, ontology or data model, or to check recorded shapes against the data.
---

# Describe the store's shapes, and record the names a person confirms

The store has no types. Entities carry attributes, and entities that carry the same attributes are the same kind of thing: a **shape**.
- You read the shapes off `stats`.
- A person confirms their names.
- You record the names.

Shapes stay derived from the data. Only their names are declared.

## Vocabulary

From factstore-skills:
- `shape/name` (identity): the confirmed name, such as "Purchase order". Address a shape by it: `["shape/name", "Purchase order"]`.
- `shape/signature` (ref, many): each attribute every entity of the shape carries, given as the attribute's own entity, `["fs/ident", "po/number"]`. An entity belongs to the shape when it carries all of them.
- `shape/doc`: one line on what the shape's entities are.

## Steps

### 1. Read what is already named

```sql
select n.v as shape, i.v as attribute
from "shape/name" n join "shape/signature" s using (e) join "fs/ident" i on i.e = s.v
order by 1, 2
```

### 2. Read the stats

Call `stats` with a `limit` high enough that `omitted_signatures` is 0. In a large store, go namespace by namespace with `namespaces`. Read all three parts:
- `attributes`: what is in use, and how much;
- `signatures`: which attributes occur together, and on how many entities;
- `refs`: which signatures point at which.

### 3. Group signatures into shapes

- **Same thing, optional attributes.** Signatures that share an identity attribute and differ only by optional attributes are one shape. Products with and without marketplace IDs are one shape.
- **Different identity, different shape.** Signatures that share most attributes but carry different identity attributes are different shapes. A shop's order line and a marketplace's order line both carry `core/part_of` and `line/sku`, but they are two shapes.
- **The shape's signature** is the attributes all of its signatures share. The rest are optional; note the share of the shape's entities that carry each.
- **Namespaces are a hint, not the rule.** `core/` attributes cross every namespace, and a shape can carry attributes from several.
- **Fragments are gaps, not shapes.** An entity holding only an identity attribute, because something referred to it before its own data arrived, is a fragment. Report fragments with their counts, such as "41 POs named by inspections have no other facts".
  - An index entry that only ever carries its ID, such as an order indexed by its marketplace ID, is a shape.
  - Its refs tell the two apart. A shape has many entities, and other shapes point at it in a regular way.
- **Account for every entity.** Each signature goes to one shape or to the gaps.

The store's own record-keeping appears in the stats too: documents (`document/`) and recorded shapes (`shape/`). Describe documents as a shape like any other. Leave shapes out of the proposal.

### 4. Read the relationships

From `refs`, note which shape points at which, and through which attribute. For example:
- Purchase order line, `core/part_of`, Purchase order;
- Shipment line, `shipment_line/po_line`, Purchase order line.

### 5. Propose, and wait

Show a table. For each shape give:
- a name the business would use: singular and plain, like "Purchase order" or "Shipment line";
- its entity count;
- its signature;
- its optional attributes, with the share of entities that carry each;
- its relationships.

List the gaps after the table. Ask the person to confirm, rename or drop each name. **Record nothing until they answer.**

### 6. Record the confirmed names

Record them in one transaction:

```json
[{"e": ["shape/name", "Purchase order"], "a": "shape/doc", "v": "An order we place with a supplier for goods."},
 {"e": ["shape/name", "Purchase order"], "a": "shape/signature", "v": ["fs/ident", "po/number"]},
 {"e": ["shape/name", "Purchase order"], "a": "shape/signature", "v": ["fs/ident", "po/supplier"]},
 {"e": "tmp:tx", "a": "core/on_behalf_of", "v": 1234}]
```

- `core/on_behalf_of` records who confirmed. Find their actor with `query` on `"fs/name"`, and leave the fact out if they have none.
- Record a shape's signature exactly as you proposed it, with every attribute its entities all carry.
- A name the person changed is recorded as they gave it.

## Re-running

Compare the recorded shapes with the current stats, and propose changes the same way:
- **A shape no entity matches any more,** or one whose count changed sharply: report it.
- **An attribute now on every entity of a shape,** or a signature attribute now missing from some: propose the new signature. Once it is confirmed, assert the added attributes and retract the dropped ones.
- **Signatures that fit no recorded shape:** propose new shapes.
- **A rename** is a new `shape/name` asserted on the same entity, addressed by its entity ID. Never rename a confirmed shape without the person.
