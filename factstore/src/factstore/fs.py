"""The kernel's own attributes, in the reserved fs/ namespace.

They have fixed entity IDs so the schema's triggers can name them. Entity IDs
below 1000 are reserved for the kernel.
"""

from dataclasses import dataclass

IDENT = 1
TYPE = 2
CARDINALITY = 3
UNIQUE = 4
DOC = 5
DISTINCT_FROM = 6
REPLACED_BY = 7
ACTOR = 8
AT = 9
NAME = 10
EXCISED_ENTITY = 11
EXCISED_ATTRIBUTE = 12

# The actor the store's admin login acts as: bootstrap, actor creation.
ADMIN_ACTOR = 100

# Serializes every write to a store. Advisory locks are scoped to one database.
WRITER_LOCK = 7_460_216_116


@dataclass(frozen=True)
class Definition:
    id: int
    ident: str
    type: str
    cardinality: str
    unique: str
    doc: str


ATTRIBUTES = [
    Definition(IDENT, "fs/ident", "string", "one", "identity",
               "Namespaced name of an attribute, e.g. customer/email."),
    Definition(TYPE, "fs/type", "string", "one", "none",
               "Value type of an attribute: string, decimal, boolean, date, instant or ref. Never changes."),
    Definition(CARDINALITY, "fs/cardinality", "string", "one", "none",
               "Whether an entity holds one value of an attribute or many. May change from one to many only."),
    Definition(UNIQUE, "fs/unique", "string", "one", "none",
               "none, or identity: at most one entity holds each value, and lookups address entities by it."),
    Definition(DOC, "fs/doc", "string", "one", "none",
               "One-line description of an attribute. What attribute search runs over."),
    Definition(DISTINCT_FROM, "fs/distinct_from", "ref", "many", "none",
               "A near-match attribute the registrant saw and declared to mean something else."),
    Definition(REPLACED_BY, "fs/replaced_by", "ref", "one", "none",
               "The attribute that replaces this deprecated one."),
    Definition(ACTOR, "fs/actor", "ref", "one", "none",
               "Who submitted a transaction. Stamped by the kernel from the credential."),
    Definition(AT, "fs/at", "instant", "one", "none",
               "When a transaction was committed. Stamped by the kernel."),
    Definition(NAME, "fs/name", "string", "one", "none",
               "Display name of an actor."),
    Definition(EXCISED_ENTITY, "fs/excised_entity", "ref", "one", "none",
               "The entity whose facts an excision removed."),
    Definition(EXCISED_ATTRIBUTE, "fs/excised_attribute", "ref", "many", "none",
               "An attribute whose facts an excision removed; absent when all of them were."),
]

# Written only by the kernel's triggers and fs_excise().
KERNEL_ONLY = {ACTOR, AT, EXCISED_ENTITY, EXCISED_ATTRIBUTE}
# Written only by register_attribute, when an attribute is registered.
REGISTER_ONLY = {IDENT, TYPE, DISTINCT_FROM}
# Changed through transact on an attribute's entity, under the evolution rules.
SCHEMA = {CARDINALITY, UNIQUE, DOC, REPLACED_BY}
