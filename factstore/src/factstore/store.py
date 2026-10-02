"""The store and its calls: transact, register_attribute, search_attributes, excise.

query and stats arrive in M2.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

import psycopg

from . import fs, kernel, values
from .errors import ExcisionError, PermissionDenied, RegistrationRefused, TransactError
from .kernel import Attr, Change

TMP = "tmp:"
TX_TEMPID = "tmp:tx"

IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*/[a-z][a-z0-9_]*$")

# Near-match thresholds for registration, on pg_trgm scores between 0 and 1. Names are
# compared without separators, so customer/e_mail matches customer/email exactly.
NEAR_NAME = 0.6        # a near name is a match in the same namespace...
NEAR_NAME_DOC = 0.3    # ...or across namespaces when the docs also overlap this much
NEAR_DOC = 0.6         # near docs are a match whatever the names
SEARCH_FLOOR = 0.2


@dataclass(frozen=True)
class Fact:
    """A fact as written. In a dry run, entities not yet created appear as their
    temporary ID or lookup instead of an ID."""

    e: object
    a: str
    v: object
    op: str


@dataclass
class TransactResult:
    tx: int | None
    at: datetime | None
    tempids: dict[str, int]
    lookups: list[dict]
    facts: list[Fact]
    unchanged: list[int]
    dry_run: bool = False
    errors: list[dict] = field(default_factory=list)
    unknown_attributes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Attribute:
    ident: str
    type: str
    cardinality: str
    unique: str
    doc: str
    replaced_by: str | None
    score: float | None = None


@dataclass(frozen=True)
class NearMatch:
    ident: str
    doc: str
    name_similarity: float
    doc_similarity: float


@dataclass
class RegisterResult:
    tx: int | None
    registered: list[str]
    existing: list[str]


def connect(dsn: str) -> "Store":
    return Store(psycopg.connect(dsn, autocommit=True))


class Store:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def transact(self, facts: list[dict], *, dry_run: bool = False) -> TransactResult:
        """Submit assertions and retractions as one transaction. See tools.TRANSACT."""
        if not isinstance(facts, (list, tuple)):
            raise TypeError("facts must be a list of {e, a, v, op} dicts")
        with self.conn.transaction(), self.conn.cursor() as cur:
            kernel.lock(cur)
            return _Transaction(cur, kernel.load_schema(cur)).run(facts, dry_run)

    def register_attribute(self, specs: dict | list[dict]) -> RegisterResult:
        """Register attributes, all or none. See tools.REGISTER_ATTRIBUTE."""
        specs = [specs] if isinstance(specs, dict) else list(specs)
        with self.conn.transaction(), self.conn.cursor() as cur:
            kernel.lock(cur)
            return _register(cur, kernel.load_schema(cur), specs)

    def search_attributes(self, text: str, *, limit: int = 10) -> list[Attribute]:
        """Registered attributes whose name or doc resembles `text`, best first."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                select a.ident, a.type, a.cardinality, a.uniq, a.doc, r.ident,
                       greatest(word_similarity(q, lower(a.ident)), word_similarity(q, lower(a.doc))) as score
                from attr a left join attr r on r.id = a.replaced_by
                cross join (select lower(%(text)s) as q) query
                where not starts_with(a.ident, 'fs/')
                order by score desc, a.ident
                limit %(limit)s
                """,
                {"text": text, "limit": limit},
            )
            return [Attribute(*row[:6], score=round(row[6], 3)) for row in cur.fetchall() if row[6] >= SEARCH_FLOOR]

    def excise(self, entity, attributes: list[str] | None = None) -> int:
        """Physically remove facts about `entity`. Needs an excision credential. See tools.EXCISE."""
        with self.conn.transaction(), self.conn.cursor() as cur:
            schema = kernel.load_schema(cur)
            e = _resolve_for_excise(cur, schema, entity)
            ids = None
            if attributes is not None:
                unknown = [a for a in attributes if a not in schema.by_ident]
                if unknown:
                    raise ExcisionError(f"unknown attributes: {', '.join(unknown)}")
                ids = [schema.by_ident[a].id for a in attributes]
            try:
                cur.execute("select fs_excise(%s, %s)", (e, ids))
            except psycopg.errors.InsufficientPrivilege:
                raise PermissionDenied("excise needs an excision credential") from None
            except psycopg.errors.RaiseException as exc:
                raise ExcisionError(exc.diag.message_primary) from None
            return cur.fetchone()[0]


# --- transact ---------------------------------------------------------------------------


class _New:
    """An entity this transaction creates, from a temporary ID or a lookup that found nothing."""

    def __init__(self, label):
        self.label = label

    def __repr__(self):
        return f"_New({self.label!r})"


_TX = _New(TX_TEMPID)


class _Lookup:
    def __init__(self, attr: Attr, key: str, value, index: int):
        self.attr = attr
        self.key = key
        self.value = value
        self.index = index  # the first input fact using this lookup
        self.target: int | _New | None = None
        self.asserted = False  # used by at least one assertion, so it may create its entity

    @property
    def label(self):
        return [self.attr.ident, values.to_json(self.value)]


@dataclass
class _Op:
    index: int
    assert_: bool
    e: object  # int | _New | _Lookup, then int | _New once resolved
    a: Attr
    v: object  # a value, or for refs int | _New | _Lookup like e


@dataclass
class _Change:
    index: int
    e: object
    a: Attr
    v: object
    assert_: bool
    implied: bool = False  # a retraction the kernel adds for cardinality one


class _Transaction:
    def __init__(self, cur, schema: kernel.Schema):
        self.cur = cur
        self.schema = schema
        self.errors: list[dict] = []
        self.unknown: list[str] = []
        self.tempids: dict[str, _New] = {}
        self.tempids_as_e: set[str] = set()
        self.lookups: dict[tuple[int, str], _Lookup] = {}
        self.ids: dict[int, int] = {}  # existing entity ID -> first input index naming it

    def error(self, index, message: str) -> None:
        self.errors.append({"index": index, "message": message})

    def run(self, facts: list[dict], dry_run: bool) -> TransactResult:
        ops = [op for i, raw in enumerate(facts) if (op := self.parse(i, raw)) is not None]
        self.resolve(ops)
        changes, effective = ([], set()) if self.errors else self.diff(ops)
        if not self.errors:
            self.check_identity(changes)
            self.check_schema_changes(changes)
        unchanged = [i for i in range(len(facts)) if i not in effective]

        if dry_run:
            facts_out = [] if self.errors else [
                Fact(_label(c.e), c.a.ident, _label(c.v), "assert" if c.assert_ else "retract") for c in changes]
            return TransactResult(None, None, {}, self.lookup_report(), facts_out, unchanged, dry_run=True,
                                  errors=self.errors, unknown_attributes=self.unknown)
        if self.errors or self.unknown:
            raise TransactError(self.errors + [
                {"index": None, "message": f"unknown attribute {a}: find one with search_attributes"
                                           " or register it with register_attribute"} for a in self.unknown])
        if not any(c.e is not _TX for c in changes):
            return TransactResult(None, None, {}, self.lookup_report({}), [], list(range(len(facts))))
        return self.write(changes, unchanged)

    # Parsing: shape and types, nothing that needs the database.

    def parse(self, i: int, raw) -> _Op | None:
        if not isinstance(raw, dict) or not {"e", "a", "v"} <= raw.keys():
            self.error(i, "a fact is an object with e, a and v (and optionally op)")
            return None
        extra = raw.keys() - {"e", "a", "v", "op"}
        if extra:
            self.error(i, f"unexpected keys {sorted(extra)}")
            return None
        op = raw.get("op", "assert")
        if op not in ("assert", "retract"):
            self.error(i, f"op must be assert or retract, not {op!r}")
            return None
        assert_ = op == "assert"

        attr = self.schema.by_ident.get(raw["a"]) if isinstance(raw["a"], str) else None
        if attr is None:
            if isinstance(raw["a"], str) and IDENT_RE.match(raw["a"]):
                if raw["a"] not in self.unknown:
                    self.unknown.append(raw["a"])
            else:
                self.error(i, f"a must be an attribute name like customer/email, not {raw['a']!r}")
            return None
        if not self.writable(i, attr, assert_):
            return None

        e = self.entity(i, raw["e"], assert_, as_e=True)
        if attr.type == "ref":
            v = self.entity(i, raw["v"], assert_, as_e=False)
        else:
            try:
                v = values.coerce(attr.type, raw["v"])
            except values.BadValue as exc:
                self.error(i, f"{attr.ident} is a {attr.type}: {exc}")
                v = None
        if e is None or v is None:
            return None
        return _Op(i, assert_, e, attr, v)

    def writable(self, i: int, attr: Attr, assert_: bool) -> bool:
        if attr.id in fs.KERNEL_ONLY:
            self.error(i, f"{attr.ident} is written by the kernel only")
            return False
        if attr.id in fs.REGISTER_ONLY:
            self.error(i, f"{attr.ident} is set by register_attribute and never changes")
            return False
        if attr.id in fs.SCHEMA and not assert_ and attr.id != fs.REPLACED_BY:
            self.error(i, f"{attr.ident} cannot be retracted; assert the new value")
            return False
        if attr.replaced_by is not None and assert_:
            replacement = self.schema.by_id[attr.replaced_by].ident
            self.error(i, f"{attr.ident} is deprecated: use {replacement}")
            return False
        return True

    def entity(self, i: int, raw, assert_: bool, *, as_e: bool):
        if isinstance(raw, bool):
            pass
        elif isinstance(raw, int):
            if raw > 0:
                self.ids.setdefault(raw, i)
                return raw
        elif isinstance(raw, str):
            if raw == TX_TEMPID:
                return _TX
            if raw.startswith(TMP) and len(raw) > len(TMP):
                if as_e:
                    self.tempids_as_e.add(raw)
                return self.tempids.setdefault(raw, _New(raw))
        elif isinstance(raw, (list, tuple)) and len(raw) == 2 and isinstance(raw[0], str):
            return self.lookup(i, raw, assert_)
        self.error(i, f"{raw!r} is not an entity: use an entity ID, a temporary ID like \"tmp:order\","
                      " or a lookup like [\"shopify/order_id\", \"1234\"]")
        return None

    def lookup(self, i: int, raw, assert_: bool) -> _Lookup | None:
        attr = self.schema.by_ident.get(raw[0])
        if attr is None:
            self.error(i, f"lookup on unknown attribute {raw[0]}")
            return None
        if attr.unique != "identity":
            self.error(i, f"{attr.ident} is not an identity attribute, so it cannot address an entity")
            return None
        try:
            if attr.type == "ref":
                if not isinstance(raw[1], int) or isinstance(raw[1], bool):
                    raise values.BadValue("a lookup on a ref attribute takes an entity ID")
                value = raw[1]
            else:
                value = values.coerce(attr.type, raw[1])
        except values.BadValue as exc:
            self.error(i, f"lookup {raw!r}: {exc}")
            return None
        key = values.key(attr.type, value)
        if len(key) > values.MAX_KEY_LENGTH:
            self.error(i, f"lookup {raw!r}: identity values are at most {values.MAX_KEY_LENGTH} characters")
            return None
        found = self.lookups.get((attr.id, key)) or self.lookups.setdefault((attr.id, key),
                                                                             _Lookup(attr, key, value, i))
        found.asserted |= assert_
        return found

    # Resolution: existing IDs, lookups and temporary IDs.

    def resolve(self, ops: list[_Op]) -> None:
        if self.ids:
            self.cur.execute("select x from unnest(%s::bigint[]) x where exists (select 1 from fact where e = x)",
                             (list(self.ids),))
            existing = {row[0] for row in self.cur.fetchall()}
            for id_, i in self.ids.items():
                if id_ not in existing:
                    self.error(i, f"entity {id_} does not exist")

        if self.lookups:
            pairs = list(self.lookups)
            self.cur.execute(
                "select ident.a, ident.key, ident.e from ident"
                " join unnest(%s::bigint[], %s::text[]) as k(a, key) using (a, key)",
                ([a for a, _ in pairs], [k for _, k in pairs]),
            )
            for a, key, e in self.cur.fetchall():
                self.lookups[(a, key)].target = e
            for lk in self.lookups.values():
                if lk.target is not None:
                    continue
                if lk.attr.ident.startswith("fs/") or not lk.asserted:
                    self.error(None, f"no entity has {lk.attr.ident} = {values.to_json(lk.value)!r}")
                else:
                    lk.target = _New(lk.label)
                    # Creating the entity asserts the value it was looked up by.
                    ops.append(_Op(lk.index, True, lk.target, lk.attr, lk.value))

        for name in self.tempids.keys() - self.tempids_as_e:
            self.error(None, f"{name} is used as a value but never as an entity, so nothing would describe it")

        for op in ops:
            op.e = _target(op.e)
            if op.a.type == "ref":
                op.v = _target(op.v)

    # The diff against current state.

    def diff(self, ops: list[_Op]) -> tuple[list[_Change], set[int]]:
        groups: dict[tuple, list[_Op]] = {}
        for op in ops:
            groups.setdefault((op.e, op.a.id), []).append(op)
        current = self.current([(e, a) for e, a in groups if isinstance(e, int)])

        changes: list[_Change] = []
        effective: set[int] = set()
        for (e, a_id), group in groups.items():
            attr = group[0].a
            now = set(current.get((e, a_id), []))
            asserts = _by_value(o for o in group if o.assert_)
            retracts = _by_value(o for o in group if not o.assert_)
            both = [v for v in asserts if v in retracts]
            if both:
                for v in both:
                    self.error(retracts[v][0], f"{attr.ident} = {_label(v)!r} is both asserted and retracted")
                continue
            if attr.cardinality == "one" and len(asserts) > 1:
                self.error(group[0].index, f"{attr.ident} has cardinality one, but this transaction asserts"
                                           f" {len(asserts)} values for the same entity")
                continue

            retracted = set()
            for v, indexes in asserts.items():
                if v in now:
                    continue
                if attr.cardinality == "one":
                    for old in now:
                        changes.append(_Change(indexes[0], e, attr, old, False, implied=True))
                        retracted.add(old)
                changes.append(_Change(indexes[0], e, attr, v, True))
                effective.update(indexes)
            for v, indexes in retracts.items():
                if v in retracted:
                    effective.update(indexes)
                elif v in now:
                    changes.append(_Change(indexes[0], e, attr, v, False))
                    effective.update(indexes)
        return changes, effective

    def current(self, pairs: list[tuple[int, int]]) -> dict[tuple[int, int], list]:
        if not pairs:
            return {}
        self.cur.execute(
            "select e, a, v_string, v_decimal, v_boolean, v_date, v_instant, v_ref from cur"
            " join unnest(%s::bigint[], %s::bigint[]) as k(e, a) using (e, a)",
            ([e for e, _ in pairs], [a for _, a in pairs]),
        )
        found: dict[tuple[int, int], list] = {}
        for e, a, *cols in self.cur.fetchall():
            found.setdefault((e, a), []).append(kernel.read_value(cols))
        return found

    # Checks on the diff.

    def check_identity(self, changes: list[_Change]) -> None:
        claims = [(c, values.key(c.a.type, c.v)) for c in changes
                  if c.assert_ and c.a.unique == "identity" and not isinstance(c.v, _New)]
        if not claims:
            return
        for c, key in claims:
            if len(key) > values.MAX_KEY_LENGTH:
                self.error(c.index, f"{c.a.ident} values are at most {values.MAX_KEY_LENGTH} characters")
        self.cur.execute(
            "select ident.a, ident.key, ident.e from ident join unnest(%s::bigint[], %s::text[]) as k(a, key)"
            " using (a, key)",
            ([c.a.id for c, _ in claims], [k for _, k in claims]),
        )
        holders = {(a, key): e for a, key, e in self.cur.fetchall()}
        freed = {(c.a.id, values.key(c.a.type, c.v)) for c in changes
                 if not c.assert_ and c.a.unique == "identity" and not isinstance(c.v, _New)}
        claimed: dict[tuple[int, str], object] = {}
        for c, key in claims:
            holder = holders.get((c.a.id, key))
            if holder is not None and holder != c.e and (c.a.id, key) not in freed:
                self.error(c.index, f"{c.a.ident} = {values.to_json(c.v)!r} already belongs to entity {holder};"
                                    f" address it with the lookup [\"{c.a.ident}\", {values.to_json(c.v)!r}]")
            if claimed.setdefault((c.a.id, key), c.e) != c.e:
                self.error(c.index, f"two entities in this transaction claim {c.a.ident} = {values.to_json(c.v)!r}")

    def check_schema_changes(self, changes: list[_Change]) -> None:
        for c in changes:
            if c.a.id not in fs.SCHEMA or c.implied:
                continue
            target = self.schema.by_id.get(c.e) if isinstance(c.e, int) else None
            if target is None:
                self.error(c.index, f"{c.a.ident} describes attributes; address one with"
                                    " [\"fs/ident\", \"customer/email\"]")
                continue
            if target.ident.startswith("fs/"):
                self.error(c.index, f"{target.ident} is a kernel attribute and cannot change")
                continue
            if c.a.id == fs.CARDINALITY and c.v != "many":
                self.error(c.index, f"cardinality of {target.ident} may change from one to many only")
            elif c.a.id == fs.UNIQUE:
                self.check_new_identity(c, target)
            elif c.a.id == fs.DOC and (not c.v.strip() or "\n" in c.v):
                self.error(c.index, "a doc is one non-empty line")
            elif c.a.id == fs.REPLACED_BY and c.assert_:
                self.check_replacement(c, target)

    def check_new_identity(self, c: _Change, target: Attr) -> None:
        if c.v != "identity":
            self.error(c.index, f"uniqueness of {target.ident} may change from none to identity only")
            return
        if target.type == "boolean":
            self.error(c.index, "a boolean attribute cannot be an identity")
            return
        holders: dict[str, set[int]] = {}
        for e, value in _current_values(self.cur, target):
            holders.setdefault(values.key(target.type, value), set()).add(e)
        too_long = [k for k in holders if len(k) > values.MAX_KEY_LENGTH]
        collisions = {k: es for k, es in holders.items() if len(es) > 1}
        if too_long:
            self.error(c.index, f"{target.ident} has values longer than {values.MAX_KEY_LENGTH} characters")
        if collisions:
            sample = "; ".join(f"{k!r} on entities {sorted(es)}" for k, es in list(collisions.items())[:5])
            self.error(c.index, f"{target.ident} cannot become an identity: {len(collisions)} values are held"
                                f" by more than one entity ({sample})")

    def check_replacement(self, c: _Change, target: Attr) -> None:
        replacement = self.schema.by_id.get(c.v) if isinstance(c.v, int) else None
        if replacement is None or replacement.ident.startswith("fs/"):
            self.error(c.index, "fs/replaced_by must point at a registered attribute")
            return
        seen = {target.id}
        while replacement is not None:
            if replacement.id in seen:
                self.error(c.index, f"replacing {target.ident} with {self.schema.by_id[c.v].ident} makes a cycle")
                return
            seen.add(replacement.id)
            replacement = self.schema.by_id.get(replacement.replaced_by)

    # Writing.

    def write(self, changes: list[_Change], unchanged: list[int]) -> TransactResult:
        tx = kernel.begin_tx(self.cur)
        new = list(dict.fromkeys(x for c in changes for x in (c.e, c.v) if isinstance(x, _New) and x is not _TX))
        ids = dict(zip(new, kernel.allocate(self.cur, len(new))))
        ids[_TX] = tx

        def real(x):
            return ids[x] if isinstance(x, _New) else x

        written = [Change(real(c.e), c.a, real(c.v) if c.a.type == "ref" else c.v, c.assert_) for c in changes]
        kernel.write(self.cur, tx, written)
        self.apply_schema_changes(written)

        self.cur.execute("select at from tx where id = %s", (tx,))
        at = self.cur.fetchone()[0]
        tempids = {name: ids[n] for name, n in self.tempids.items() if n in ids}
        if any(c.e is _TX for c in changes):
            tempids[TX_TEMPID] = tx
        lookups = self.lookup_report(ids)
        facts = [Fact(c.e, c.a.ident, c.v, "assert" if c.assert_ else "retract") for c in written]
        return TransactResult(tx, at, tempids, lookups, facts, unchanged)

    def apply_schema_changes(self, written: list[Change]) -> None:
        for c in written:
            if c.a.id == fs.CARDINALITY and c.assert_:
                self.cur.execute("update attr set cardinality = %s where id = %s", (c.v, c.e))
            elif c.a.id == fs.DOC and c.assert_:
                self.cur.execute("update attr set doc = %s where id = %s", (c.v, c.e))
            elif c.a.id == fs.REPLACED_BY:
                # A replacement's implied retraction comes before its assertion.
                self.cur.execute("update attr set replaced_by = %s where id = %s", (c.v if c.assert_ else None, c.e))
            elif c.a.id == fs.UNIQUE and c.assert_:
                self.cur.execute("update attr set uniq = 'identity' where id = %s", (c.e,))
                target = self.schema.by_id[c.e]
                rows = [(target.id, values.key(target.type, v), e) for e, v in _current_values(self.cur, target)]
                self.cur.executemany("insert into ident (a, key, e) values (%s, %s, %s)", rows)

    def lookup_report(self, ids: dict | None = None) -> list[dict]:
        report = []
        for lk in self.lookups.values():
            created = isinstance(lk.target, _New)
            e = (ids[lk.target] if created else lk.target) if ids is not None else _label(lk.target)
            report.append({"lookup": lk.label, "e": e, "created": created})
        return report


def _target(x):
    return x.target if isinstance(x, _Lookup) else x


def _by_value(ops) -> dict:
    grouped: dict = {}
    for op in ops:
        grouped.setdefault(op.v, []).append(op.index)
    return grouped


def _label(x):
    if isinstance(x, _New):
        return x.label
    return x


def _current_values(cur, attr: Attr) -> list[tuple[int, object]]:
    column = values.COLUMN[attr.type]
    cur.execute(f"select e, {column} from cur where a = %s", (attr.id,))
    return cur.fetchall()


def _resolve_for_excise(cur, schema: kernel.Schema, entity) -> int:
    if isinstance(entity, int) and not isinstance(entity, bool):
        return entity
    if isinstance(entity, (list, tuple)) and len(entity) == 2:
        attr = schema.by_ident.get(entity[0])
        if attr is None or attr.unique != "identity":
            raise ExcisionError(f"{entity[0]} is not an identity attribute")
        try:
            value = entity[1] if attr.type == "ref" else values.coerce(attr.type, entity[1])
        except values.BadValue as exc:
            raise ExcisionError(str(exc)) from None
        cur.execute("select e from ident where a = %s and key = %s", (attr.id, values.key(attr.type, value)))
        row = cur.fetchone()
        if row is None:
            raise ExcisionError(f"no entity has {attr.ident} = {entity[1]!r}")
        return row[0]
    raise ExcisionError("entity must be an entity ID or a lookup like [\"shopify/customer_id\", \"42\"]")


# --- register_attribute ---------------------------------------------------------------


@dataclass(frozen=True)
class _Spec:
    ident: str
    type: str
    cardinality: str
    unique: str
    doc: str
    distinct_from: tuple[str, ...]


def _register(cur, schema: kernel.Schema, specs: list[dict]) -> RegisterResult:
    errors: list[dict] = []
    batch: dict[str, _Spec] = {}
    existing: list[str] = []
    for i, raw in enumerate(specs):
        spec = _parse_spec(i, raw, errors)
        if spec is None:
            continue
        if spec.ident in batch or spec.ident in existing:
            errors.append({"index": i, "message": f"{spec.ident} appears twice in this batch"})
            continue
        old = schema.by_ident.get(spec.ident)
        if old is None:
            batch[spec.ident] = spec
        elif (old.type, old.cardinality, old.unique) == (spec.type, spec.cardinality, spec.unique):
            existing.append(spec.ident)
        else:
            errors.append({"index": i, "message": f"{spec.ident} is already registered as {old.type},"
                                                  f" cardinality {old.cardinality}, unique {old.unique}"})
        for d in spec.distinct_from:
            if d not in schema.by_ident and not any(isinstance(r, dict) and r.get("ident") == d for r in specs):
                errors.append({"index": i, "message": f"distinct_from names {d}, which is not registered"})

    new = list(batch.values())
    refused = _near_matches(cur, new, batch) if new else {}
    if errors or refused:
        raise RegistrationRefused(refused, errors)
    if not new:
        return RegisterResult(None, [], existing)

    tx = kernel.begin_tx(cur)
    ids = dict(zip((s.ident for s in new), kernel.allocate(cur, len(new))))
    cur.executemany(
        "insert into attr (id, ident, type, cardinality, uniq, doc) values (%s, %s, %s, %s, %s, %s)",
        [(ids[s.ident], s.ident, s.type, s.cardinality, s.unique, s.doc) for s in new],
    )
    changes = []
    for s in new:
        e = ids[s.ident]
        changes += [Change(e, schema.fs(fs.IDENT), s.ident, True),
                    Change(e, schema.fs(fs.TYPE), s.type, True),
                    Change(e, schema.fs(fs.CARDINALITY), s.cardinality, True),
                    Change(e, schema.fs(fs.UNIQUE), s.unique, True),
                    Change(e, schema.fs(fs.DOC), s.doc, True)]
        changes += [Change(e, schema.fs(fs.DISTINCT_FROM), ids.get(d) or schema.by_ident[d].id, True)
                    for d in s.distinct_from]
    kernel.write(cur, tx, changes)
    return RegisterResult(tx, [s.ident for s in new], existing)


def _parse_spec(i: int, raw, errors: list[dict]) -> _Spec | None:
    def bad(message):
        errors.append({"index": i, "message": message})

    if not isinstance(raw, dict):
        bad("an attribute is an object with ident, type, cardinality and doc")
        return None
    extra = raw.keys() - {"ident", "type", "cardinality", "unique", "doc", "distinct_from"}
    if extra:
        bad(f"unexpected keys {sorted(extra)}")
        return None
    ident, type_, card = raw.get("ident"), raw.get("type"), raw.get("cardinality")
    unique, doc = raw.get("unique", "none"), raw.get("doc")
    distinct_from = raw.get("distinct_from", [])
    ok = True
    if not isinstance(ident, str) or not IDENT_RE.match(ident):
        bad(f"ident must be namespace/name in lowercase letters, digits and underscores, not {ident!r}")
        ok = False
    elif ident.startswith("fs/"):
        bad("the fs/ namespace is reserved for the kernel")
        ok = False
    if type_ not in values.TYPES:
        bad(f"type must be one of {', '.join(values.TYPES)}, not {type_!r}")
        ok = False
    if card not in ("one", "many"):
        bad(f"cardinality must be one or many, not {card!r}")
        ok = False
    if unique not in ("none", "identity"):
        bad(f"unique must be none or identity, not {unique!r}")
        ok = False
    elif unique == "identity" and type_ == "boolean":
        bad("a boolean attribute cannot be an identity")
        ok = False
    if not isinstance(doc, str) or not doc.strip() or "\n" in doc:
        bad("doc must be one non-empty line saying what the value means")
        ok = False
    if not isinstance(distinct_from, list) or not all(isinstance(d, str) for d in distinct_from):
        bad("distinct_from must be a list of attribute names")
        ok = False
    if not ok:
        return None
    return _Spec(ident, type_, card, unique, doc.strip(), tuple(distinct_from))


def _near_matches(cur, new: list[_Spec], batch: dict[str, _Spec]) -> dict[str, list[NearMatch]]:
    """Near matches for each new attribute that its registrant has not declared distinct."""
    cur.execute(
        """
        with new (ident, doc) as (select * from unnest(%s::text[], %s::text[])),
        candidate (ident, doc) as (
          select ident, doc from attr where not starts_with(ident, 'fs/') and replaced_by is null
          union all
          select ident, doc from new
        ),
        named as (
          select n.ident as n_ident, n.doc as n_doc, c.ident as c_ident, c.doc as c_doc,
                 regexp_replace(lower(split_part(n.ident, '/', 2)), '[^a-z0-9]', '', 'g') as n_name,
                 regexp_replace(lower(split_part(c.ident, '/', 2)), '[^a-z0-9]', '', 'g') as c_name
          from new n cross join candidate c
          where n.ident <> c.ident
        )
        select n_ident, c_ident, c_doc,
               greatest(word_similarity(n_name, c_name), word_similarity(c_name, n_name)),
               similarity(lower(n_doc), lower(c_doc)),
               split_part(n_ident, '/', 1) = split_part(c_ident, '/', 1)
        from named
        """,
        ([s.ident for s in new], [s.doc for s in new]),
    )
    refused: dict[str, list[NearMatch]] = {}
    for ident, other, doc, name_sim, doc_sim, same_namespace in cur.fetchall():
        if not _is_near(name_sim, doc_sim, same_namespace):
            continue
        if other in batch[ident].distinct_from or (other in batch and ident in batch[other].distinct_from):
            continue
        refused.setdefault(ident, []).append(NearMatch(other, doc, round(name_sim, 3), round(doc_sim, 3)))
    return refused


def _is_near(name_sim: float, doc_sim: float, same_namespace: bool) -> bool:
    if name_sim >= NEAR_NAME and (same_namespace or doc_sim >= NEAR_NAME_DOC):
        return True
    return doc_sim >= NEAR_DOC
