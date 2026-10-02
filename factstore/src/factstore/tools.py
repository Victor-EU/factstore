"""The MCP tools: names, descriptions and input schemas.

These descriptions are the primary documentation (design §2): a model should be able
to use the store from them alone. Fix confusion here, not in prompts.

`query` is SQL over a view per attribute (design open question 1, decided by the M0 spike).
"""

_ENTITY = {
    "description": "An entity ID (integer); a temporary ID for a new entity (\"tmp:order\"); or a lookup "
                   "[identity attribute, value] such as [\"shopify/order_id\", \"1234\"].",
    "anyOf": [
        {"type": "integer", "minimum": 1},
        {"type": "string", "pattern": "^tmp:.+"},
        {"type": "array", "prefixItems": [{"type": "string"}, {}], "minItems": 2, "maxItems": 2},
    ],
}

TRANSACT = {
    "name": "transact",
    "description": """\
Record facts as one transaction. A fact says an entity has a value for an attribute. Nothing is \
ever overwritten: to correct a value, assert the new one; to withdraw one, retract it.

Each fact is {"e", "a", "v"} with an optional "op": "assert" (the default) or "retract".
- e: the entity. An entity ID; a temporary ID like "tmp:order" for a new entity, reused to refer \
to it elsewhere in the same call; or a lookup like ["shopify/order_id", "1234"], which addresses \
the entity holding that value of an identity attribute and creates it if there is none. \
"tmp:tx" is this transaction itself: use it to record evidence or confidence for the write.
- a: a registered attribute, e.g. "customer/email". Unknown attributes are rejected: find one \
with search_attributes, or register it with register_attribute.
- v: a value of the attribute's type. string; decimal as a string, e.g. "99.50", never a float; \
boolean; date as "YYYY-MM-DD"; instant as ISO 8601 with a timezone, e.g. \
"2026-10-01T09:30:00+08:00"; ref as an entity ID, temporary ID or lookup.

For an attribute of cardinality one, asserting a new value replaces the current one, and the \
retraction is recorded. So a value that changes (a slipped ETD, a new status, a corrected \
amount) is a new assertion on the same attribute; the old value stays in history. Never register \
a new attribute for a new version of a value, such as revised_etd or previous_status. Asserting a value the entity already has, or retracting one it does not \
have, changes nothing and is reported as unchanged. If nothing changes, no transaction is written.

The kernel stamps who wrote and when from your credential; you cannot set them. Provenance \
belongs to the transaction, so facts with different evidence or confidence go in separate calls.

To evolve an attribute, transact on its entity, addressed as ["fs/ident", "customer/email"]: \
fs/doc to improve its doc; fs/cardinality "many" (from one, never back); fs/unique "identity" \
(if no two entities share a value); fs/replaced_by pointing at the attribute that replaces it.

With dry_run: true, nothing is written; the result shows what would be, including attributes \
that would need registering.

Returns the transaction ID, the IDs given to temporary IDs, each lookup's entity and whether it \
was created, the facts written, and the indexes of input facts that changed nothing. On \
rejection nothing is written and every problem is listed.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "e": _ENTITY,
                        "a": {"type": "string", "description": "A registered attribute, namespace/name."},
                        "v": {"description": "A value of the attribute's type; for refs, an entity as in e."},
                        "op": {"enum": ["assert", "retract"], "default": "assert"},
                    },
                    "required": ["e", "a", "v"],
                    "additionalProperties": False,
                },
            },
            "dry_run": {"type": "boolean", "default": False},
        },
        "required": ["facts"],
        "additionalProperties": False,
    },
}

REGISTER_ATTRIBUTE = {
    "name": "register_attribute",
    "description": """\
Register new attributes. Attributes are the store's vocabulary and deliberately expensive to \
add: search first (search_attributes) and reuse an existing attribute if it fits. A new or \
revised value of something an attribute already holds is not a new attribute: assert it with \
transact, and the store keeps the old one in history.

Each attribute has:
- ident: "namespace/name" in lowercase letters, digits and underscores, e.g. \
"supplier/payment_terms". The namespace is usually the kind of thing described, or the source \
system for its identifiers ("shopify/order_id"). fs/ is reserved.
- type: string, decimal, boolean, date, instant or ref (a reference to another entity).
- cardinality: one (a new value replaces the old) or many (values accumulate).
- doc: one line saying what the value means. Search runs over it, so write it for the next \
reader deciding whether to reuse this attribute.
- unique: "none" (default) or "identity" for identifiers such as "shopify/order_id": at most one \
entity holds each value, and lookups can address entities by it.
- distinct_from: attributes you have seen and judged to mean something else (see below).

The kernel compares each new attribute with existing ones itself. If any are near matches, \
registration is refused and the matches are returned with their docs. Reuse one of them, or \
register again listing them in distinct_from; that statement is recorded. distinct_from says \
the match means something different, not that you want the same kind of value on another kind \
of entity: if po/pi_number exists, a proforma invoice number belongs on the PO, not in a new \
shipment/pi_number. A batch registers in \
one transaction or not at all. Registering an attribute that already exists with the same type, \
cardinality and uniqueness changes nothing.

Attributes change in one direction only: type never; cardinality from one to many; uniqueness \
from none to identity. See transact for how.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "attributes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "ident": {"type": "string", "pattern": "^[a-z][a-z0-9_]*/[a-z][a-z0-9_]*$"},
                        "type": {"enum": ["string", "decimal", "boolean", "date", "instant", "ref"]},
                        "cardinality": {"enum": ["one", "many"]},
                        "doc": {"type": "string", "minLength": 1},
                        "unique": {"enum": ["none", "identity"], "default": "none"},
                        "distinct_from": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["ident", "type", "cardinality", "doc"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["attributes"],
        "additionalProperties": False,
    },
}

SEARCH_ATTRIBUTES = {
    "name": "search_attributes",
    "description": """\
Find registered attributes by name or meaning, best match first, with their type, cardinality, \
uniqueness and doc. A deprecated attribute shows what replaced it. Use it before registering an \
attribute, and before writing when unsure which attribute fits.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Words describing the value, or part of a name."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}

WHAT_WAS_KNOWN = """\
as_of reads when facts were recorded, not when they held in the world, so a store loaded today \
from a year of documents has nothing as of last month. Read history instead, keeping each value \
whose transaction's evidence (core/evidence) was issued by the date (document/issued_at), the \
latest issued winning. Each PO's ETD as known at the start of 15 March 2026 in New York:
select distinct on (h.e) h.e, h.v from history."po/etd" h
join "core/evidence" ev on ev.e = h.tx
join "document/issued_at" d on d.e = ev.v
where h.op = 'assert' and d.v < '2026-03-15T00:00:00-04:00'
order by h.e, d.v desc, h.tx desc"""

QUERY = {
    "name": "query",
    "description": """\
Read the store with one SQL statement (PostgreSQL), read-only. Returns columns and rows.

The store holds facts: an entity has a value for an attribute. Every attribute is a view named \
after it, e.g. "po/status"; always double-quote the name. Columns:
- e: the entity (bigint)
- v: the value, typed: text, numeric, boolean, date, timestamptz, or bigint (another entity's e) \
for refs
- tx: the transaction that asserted the value
One row per entity and value: at most one per entity for a cardinality-one attribute, several \
for a many. An entity without a value has no row, so left join optional attributes. Join \
attributes of one entity on e: from "po/number" n join "po/status" s using (e). Find attribute \
names with search_attributes, and what kinds of entity exist with stats.

Refs: v is the e of the entity pointed to. Forward: join "supplier/code" c on c.e = s.v. \
Backward, join the other way: a PO's lines are the "core/part_of" rows whose v is the PO.

Values: text compares as text; decimals are exact; dates are written '2026-04-01'; instants \
'2026-04-01T00:00:00Z', returned in UTC.

Transactions are entities: "fs/at" is when one committed, "fs/actor" refs who wrote it, and \
"fs/name" holds the actor's name. Join a value's tx to them to see who recorded it and when. \
Transaction IDs increase in commit order.

History: schema history has the same views over every fact ever recorded, replaced values \
included, with columns e, v, tx and op ('assert' or 'retract'). Replacing a value of a \
cardinality-one attribute retracts the old one in the same transaction. Every value an entity's \
attribute has had, in order: select v, tx from history."po/etd" where e = 123 and op = 'assert' \
order by tx.

Joins multiply rows: joining an entity to two of its many-valued parts (say, a PO to its lines \
and to its shipments) repeats each line once per shipment, and sums double. Aggregate each \
path in its own subquery, or join along one path only.

as_of: a transaction ID, or an instant with a timezone. Every view, history included, then shows \
the store as it was after that transaction. Pass as_of rather than filtering on tx.

What was known on a date: """ + WHAT_WAS_KNOWN + """

facts(e, a, v, tx) lists every value as text with its attribute name: \
select a, v from facts where e = 123.

Following a ref through any number of hops takes a recursive CTE. Walk to the end of the chain, \
then back down to everything that leads there. For example, every account that is the same \
customer as account 42, where duplicates point at the account they duplicate with core/same_as:
with recursive up(e) as (
  select 42::bigint union select s.v from up join "core/same_as" s on s.e = up.e),
root as (select e from up where e not in (select e from "core/same_as")),
down(e) as (
  select e from root union select s.e from down join "core/same_as" s on s.v = down.e)
select e from down

One statement, 10 s, at most 1000 rows (truncated says if there were more). Nothing you run \
can change the store; write with transact.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "One SELECT or WITH ... SELECT statement."},
            "as_of": {"description": "Read the store as of this transaction ID, or this ISO 8601 instant with a timezone.",
                      "anyOf": [{"type": "integer", "minimum": 1}, {"type": "string"}]},
        },
        "required": ["sql"],
        "additionalProperties": False,
    },
}

STATS = {
    "name": "stats",
    "description": """\
Describe what the store holds, counted over current state. Read it to work out the kinds of \
things the store tracks and how they connect; the store itself has no notion of types.

Returns:
- attributes: each attribute in use, with how many entities hold it and how many values in all.
- signatures: each distinct set of attributes that entities carry, with how many carry exactly \
that set, largest first, as s1, s2, ... A kind of thing is usually one signature, or a few that \
differ by optional attributes (SKUs with and without Amazon IDs, say).
- refs: for each ref attribute, how many refs go from entities of one signature to entities of \
another. This is how kinds of thing connect: order lines are core/part_of orders.
- omitted_signatures and omitted_entities: what lies beyond the limit.

A deprecated attribute is counted under the attribute that replaced it, and listed in that \
attribute's "includes". The kernel's own bookkeeping (attributes, transactions, actors) is left \
out unless include_kernel is true.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "namespaces": {"type": "array", "items": {"type": "string"},
                           "description": "Only entities with an attribute in these namespaces, e.g. [\"po\", \"po_line\"]."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50,
                      "description": "At most this many signatures."},
            "include_kernel": {"type": "boolean", "default": False},
        },
        "additionalProperties": False,
    },
}

EXCISE = {
    "name": "excise",
    "description": """\
Permanently delete the facts about one entity, for a person's request to erase their data. \
Unlike retraction, the values are gone from the log and from history. Optionally limit it to \
some attributes. The deletion is itself recorded: who, when, which entity and attributes, never \
the values. Facts about other entities that refer to this one are untouched.

Only an excision credential can do this. If the person's data also lives in a source system such \
as Shopify, delete it there too, or the next catalogue run will bring it back.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "entity": {
                "description": "An entity ID, or a lookup such as [\"shopify/customer_id\", \"42\"].",
                "anyOf": [_ENTITY["anyOf"][0], _ENTITY["anyOf"][2]],
            },
            "attributes": {"type": "array", "items": {"type": "string"},
                           "description": "Only these attributes' facts. Omit to remove every fact about the entity."},
        },
        "required": ["entity"],
        "additionalProperties": False,
    },
}

TOOLS = [QUERY, TRANSACT, SEARCH_ATTRIBUTES, REGISTER_ATTRIBUTE, STATS, EXCISE]
