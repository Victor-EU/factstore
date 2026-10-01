"""The MCP tools: names, descriptions and input schemas.

These descriptions are the primary documentation (design §2): a model should be able
to use the store from them alone. Fix confusion here, not in prompts.

`query` is added once its language is chosen (design open question 1).
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
retraction is recorded. Asserting a value the entity already has, or retracting one it does not \
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
add: search first (search_attributes) and reuse an existing attribute if it fits.

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
register again listing them in distinct_from; that statement is recorded. A batch registers in \
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

STATS = {
    "name": "stats",
    "description": """\
Describe the store's shape: how many entities carry each attribute, which attributes occur \
together on the same entities, and which refs connect which groups of attributes. Read it to \
describe the kinds of things the store holds.""",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
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

TOOLS = [TRANSACT, REGISTER_ATTRIBUTE, SEARCH_ATTRIBUTES, STATS, EXCISE]
