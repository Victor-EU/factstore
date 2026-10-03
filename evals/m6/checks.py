"""What M6 measures without an answer key, on any round's store.

M4's and M5's scorers compare a store with the fixture's ground truth. Public data has none. These
look for what a common mistake leaves in a store, as the catalogue's step 7 does, and compare the
store with the raw files. Each returns counts only, so its result can be committed: nothing from the
data itself.
"""

import csv
import re
from pathlib import Path

from score import allowed_personal, has_attr, rows

csv.field_size_limit(1 << 24)


def identities(conn) -> list[str]:
    return [r[0] for r in rows(conn, """
        select ident from attr where uniq = 'identity' and type = 'string'
        and ident not like 'fs/%%' and ident <> 'document/hash' order by ident""")]


def column_values(folder: Path, pattern: str, column: str) -> set[str]:
    out = set()
    for path in sorted(folder.glob(pattern)):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            for row in csv.DictReader(f):
                v = (row.get(column) or "").strip()
                if v:
                    out.add(v)
    return out


def id_counts(conn, folder: Path, ids) -> dict:
    """For each kind of record, its distinct IDs in the source, and the identity attribute holding
    most of them: how many it holds, how many of the source's are missing, and how many it holds
    that the source lacks. `found_ignoring_case` allows for a catalogue that normalized the IDs."""
    held = {i: {v for (v,) in rows(conn, f'select v from current."{i}"')} for i in identities(conn)}
    out = {}
    for spec in ids:
        source = column_values(folder, spec.file, spec.column)
        best = max(held, key=lambda i: len(source & held[i]), default=None)
        found = len(source & held[best]) if best else 0
        if not found:
            out[spec.kind] = {"in_source": len(source), "attribute": None}
            continue
        lower = {v.lower() for v in held[best]}
        out[spec.kind] = {"in_source": len(source), "attribute": best, "in_store": len(held[best]),
                          "found": found, "found_ignoring_case": sum(v.lower() in lower for v in source),
                          "missing": len(source) - found, "not_in_source": len(held[best] - source)}
    return out


def bare(conn) -> dict:
    """Per identity attribute, entities holding nothing but it: what a malformed join key creates
    (catalogue step 7), or a record another skill fills later."""
    out = {}
    for ident in identities(conn):
        total, alone = rows(conn, f"""
            select count(*), count(*) filter (where not exists (
                select 1 from cur c join attr a on a.id = c.a
                where c.e = k.e and a.ident <> %s and a.ident not like 'fs/%%'))
            from current."{ident}" k""", ident)[0]
        out[ident] = {"entities": total, "bare": alone}
    return out


def personal(conn, folder: Path, columns) -> dict:
    """Values of the round's personal columns found in the store, and strings shaped like an email
    address. A message ID (`mid:...@host`, an email's document URL) isn't one. Counts only."""
    values = set()
    for pattern, column in columns:
        values |= {v.lower() for v in column_values(folder, pattern, column) if len(v) > 4}
    stored = [v for (v,) in rows(conn, "select distinct v_string from fact where v_string is not null")]
    return {"personal_values": sum(v.lower() in values for v in stored),
            "email_shaped": sum(bool(re.fullmatch(r"[^@\s:<>]+@[^@\s]+\.[a-z]+", v)) for v in stored),
            "allowed": allowed_personal(conn)}


def documents(conn) -> dict:
    """Documents recorded, and how many carry their URL and issue date (core 0.2.0)."""
    if not has_attr(conn, "document/hash"):
        return {"documents": 0}
    out = {"documents": rows(conn, 'select count(*) from current."document/hash"')[0][0]}
    for ident in ("document/url", "document/issued_at"):
        out[ident.split("/")[1]] = rows(conn, f'select count(*) from current."{ident}"')[0][0] if has_attr(conn, ident) else 0
    return out


def size(conn) -> dict:
    """The store's size: facts, entities (outside transactions and attributes) and transactions."""
    facts, entities = rows(conn, """
        select count(*), count(distinct e) filter (where e not in (select id from tx) and e not in (select id from attr))
        from fact""")[0]
    return {"facts": facts, "entities": entities, "transactions": rows(conn, "select count(*) from tx")[0][0]}
