"""stats: what the store holds, counted over current state. The raw material for describing
the ontology (design §7): the kernel only counts, the reader names the shapes.

Co-occurrence is reported as signatures: each distinct set of attributes entities carry, and
how many carry exactly that set. Any pairwise co-occurrence follows from them, and a shape
is usually one signature or a few that differ by optional attributes.

A deprecated attribute is counted under the attribute that replaces it (fs/replaced_by,
followed to the end of the chain), so readers see the vocabulary as it now stands.
"""

from dataclasses import dataclass, field

from . import kernel

DEFAULT_LIMIT = 50


@dataclass(frozen=True)
class AttributeUsage:
    ident: str
    type: str
    cardinality: str
    entities: int          # entities with at least one current value
    values: int            # current values, across those entities
    includes: list = field(default_factory=list)  # deprecated attributes counted here


@dataclass(frozen=True)
class Signature:
    id: str                # s1, s2, ... by descending entity count
    attributes: list
    entities: int


@dataclass(frozen=True)
class RefLink:
    attribute: str
    source: str            # signature of the entities holding the ref
    target: str | None     # signature of the entities referred to; None if they hold no facts
    count: int


@dataclass(frozen=True)
class Stats:
    tx: int                # the latest transaction counted
    entities: int
    attributes: list
    signatures: list
    refs: list
    omitted_signatures: int = 0   # beyond the limit
    omitted_entities: int = 0


def collect(cur, schema: kernel.Schema, *, namespaces: list[str] | None = None, limit: int = DEFAULT_LIMIT,
            include_kernel: bool = False) -> Stats:
    final = _replacements(schema)
    src = [a for a in final]
    dst = [final[a] for a in final]

    def shown(attr_ids) -> bool:
        idents = [schema.by_id[a].ident for a in attr_ids]
        if not include_kernel and all(i.startswith("fs/") for i in idents):
            return False
        return namespaces is None or any(i.split("/")[0] in namespaces for i in idents)

    tx = cur.execute("select coalesce(max(id), 0) from tx").fetchone()[0]

    # One pass gives each entity's signature, folding deprecated attributes into their replacements.
    # Signatures are numbered once so the ref count groups by integers, not arrays.
    cur.execute("""
        create temp table fs_sig on commit drop as
        select e, attrs, dense_rank() over (order by attrs) as sid from (
            select c.e, array_agg(distinct coalesce(m.dst, c.a) order by coalesce(m.dst, c.a)) as attrs
            from cur c left join unnest(%s::bigint[], %s::bigint[]) as m(src, dst) on m.src = c.a
            group by c.e) s""", (src, dst))
    cur.execute("create index on fs_sig (e)")
    cur.execute("analyze fs_sig")
    counts = cur.execute("select min(attrs), sid, count(*) from fs_sig group by sid").fetchall()
    kept = sorted(((attrs, sid, n) for attrs, sid, n in counts if shown(attrs)), key=lambda r: (-r[2], r[0]))
    ids = {sid: f"s{i}" for i, (_, sid, _) in enumerate(kept, 1)}
    listed = kept[:limit]
    signatures = [Signature(ids[sid], sorted(schema.by_id[a].ident for a in attrs), n) for attrs, sid, n in listed]
    omitted = kept[limit:]

    usage_rows = cur.execute("""
        select coalesce(m.dst, c.a), count(distinct c.e), count(*)
        from cur c left join unnest(%s::bigint[], %s::bigint[]) as m(src, dst) on m.src = c.a
        group by 1""", (src, dst)).fetchall()
    included = {}
    for old, new in final.items():
        included.setdefault(new, []).append(schema.by_id[old].ident)
    attributes = []
    for a, entities, values_ in sorted(usage_rows, key=lambda r: schema.by_id[r[0]].ident):
        attr = schema.by_id[a]
        if not include_kernel and attr.ident.startswith("fs/"):
            continue
        if namespaces is not None and attr.ident.split("/")[0] not in namespaces:
            continue
        attributes.append(AttributeUsage(attr.ident, attr.type, attr.cardinality, entities, values_,
                                         sorted(included.get(a, []))))

    listed_ids = {ids[sid] for _, sid, _ in listed}
    ref_rows = cur.execute("""
        select coalesce(m.dst, c.a), s.sid, t.sid, count(*)
        from cur c
        join fs_sig s on s.e = c.e
        left join fs_sig t on t.e = c.v_ref
        left join unnest(%s::bigint[], %s::bigint[]) as m(src, dst) on m.src = c.a
        where c.v_ref is not null
        group by 1, 2, 3""", (src, dst)).fetchall()
    refs = []
    for a, s_sid, t_sid, n in ref_rows:
        source = ids.get(s_sid)
        target = ids.get(t_sid) if t_sid is not None else None
        if source not in listed_ids or (t_sid is not None and target not in listed_ids):
            continue
        refs.append(RefLink(schema.by_id[a].ident, source, target, n))
    refs.sort(key=lambda r: (-r.count, r.attribute))

    return Stats(tx=tx, entities=sum(n for _, _, n in kept), attributes=attributes, signatures=signatures,
                 refs=refs, omitted_signatures=len(omitted), omitted_entities=sum(n for _, _, n in omitted))


def _replacements(schema: kernel.Schema) -> dict[int, int]:
    """Deprecated attribute ID -> the ID at the end of its fs/replaced_by chain."""
    final = {}
    for attr in schema.by_id.values():
        seen, a = {attr.id}, attr
        while a.replaced_by is not None and a.replaced_by not in seen:
            seen.add(a.replaced_by)
            a = schema.by_id[a.replaced_by]
        if a.id != attr.id:
            final[attr.id] = a.id
    return final
