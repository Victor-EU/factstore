"""Round 4: reading orders and invoices in layouts the skill hasn't seen.

DocILE, the first choice, had nothing under its download token (2026-10-03), and its maintainers
had left access requests unanswered since July. VRDU's ad-buy forms stand in (Google Research,
2023): 641 TV stations' orders, contracts and invoices for political airtime, from the FCC's public
files for the 2012 and 2020 elections. A station sells airtime as a supplier sells goods: an order
with a number, an advertiser and its agency, flight dates, line items and a gross amount. What makes
it hard:

- dozens of layouts, from several traffic systems, more than 300 stations and two elections;
- line items: 12 to a form at the median, up to 110;
- 35 scans with no text layer;
- one advertiser under several names, such as "Congressional Leadership Fund" and
  "POL/Congressional Leadership Fund PAC": question 5;
- advertisers a station labels by their candidate, "POL/Ben Salango/Governor/WV/Dem": a person's
  name, so the store's rule keeps it out unless the business allows it. The mark doesn't count
  these labels, and reports them;
- contract numbers that repeat across forms: a revised order, or two stations' own numbering;
- people: salespeople, buyers, phone numbers and email addresses on most forms;
- no package: an airtime order isn't one of ecom-ops' purchase orders.

The labels are spans of Google's OCR text, one per field and line item. Some cut a date in two
("05/27/20-05", "/28/20") or run two fields together, so a label that doesn't read as its type is
left out of the key, and counted. The questions' answers were read from the PDFs by hand.

Question 5 first asked for Ben Salango's campaign, which two forms name only by the candidate. The
second trial, keeping the person's name out as the rule says, couldn't answer it. It now asks for a
committee no form names by a person (2026-10-03).
"""

import gzip
import hashlib
import json
import logging
import random
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import round5
from score import rows

DOCUMENTS = "documents"
LABELS = Path(__file__).resolve().parents[2] / "data" / "vrdu" / "repo" / "ad-buy-form" / "main" / "dataset.jsonl.gz"

# Each labelled field, read as its kind. The pass mark counts the first four; the rest are reported.
FIELDS = {"contract_num": "id", "property": "name", "advertiser": "name", "gross_amount": "amount",
          "agency": "name", "product": "name", "flight_from": "date", "flight_to": "date", "tv_address": "name"}
MARKED = ("contract_num", "property", "advertiser", "gross_amount")
LINE = {"program_desc": "name", "program_start_date": "date", "program_end_date": "date", "sub_amount": "amount"}

QUESTIONS = (
    {"id": 1, "text": "What are the gross and net amounts of WPNT's contract 4339717?",
     "columns": ["gross amount", "net amount"], "forms": ("63ad699d-fa76-17bb-1bc5-ab2fafd0a2a3.pdf",)},
    {"id": 2, "text": "List the line items of KJZZ's contract 4396160: programme, start date, end date and amount.",
     "columns": ["programme", "start date", "end date", "amount"], "forms": ("e910d31f-0c5a-5041-1a4d-1f1b39606992.pdf",)},
    {"id": 3, "text": "Which advertiser and agency is WOTV's order 2534652 for, and what are its flight dates?",
     "columns": ["advertiser", "agency", "flight start", "flight end"],
     "forms": ("2eb5eaa6-3f56-cb68-b3c8-76abab26dc0c.pdf",)},
    {"id": 4, "text": "How many line items does WOVA's order 1625712 have, and what are its gross and net amounts?",
     "columns": ["line items", "gross amount", "net amount"], "forms": ("c9204d82-eacf-ba02-dc18-d2c10df9e9a9.pdf",)},
    {"id": 5, "text": "Which orders did the Congressional Leadership Fund place, under any of its names? Give each "
                      "order's number, station and gross amount.",
     "columns": ["order number", "station", "gross amount"],
     "forms": ("0892f433-a82d-eae3-d2ae-e578edea8656.pdf", "cffdc770-78d9-48d0-05bb-dad8a62bf909.pdf",
               "d02b547f-6489-aaa4-57e1-f01e245c6c0c.pdf", "e92e9977-b08c-2fe5-6276-f0e10d5d63c0.pdf",
               "ee234d1a-3dcb-094c-ae17-582e68fa9b1d.pdf")},
    {"id": 6, "text": "What are the gross and net amounts of KOAT's contract 903873 with the NRSC?",
     "columns": ["gross amount", "net amount"], "forms": ("414817-collect-files-53928-political-file-2012-non.pdf",)},
)

# Read from the PDFs by hand. Question 6's form is a scan.
ANSWERS = {
    1: [["900", "765"]],
    2: [["Wheel of Fortune", date(2020, 6, 23), date(2020, 6, 23), "125"],
        ["Wheel of Fortune", date(2020, 6, 26), date(2020, 6, 26), "125"],
        ["Jeopardy", date(2020, 6, 22), date(2020, 6, 22), "150"],
        ["Jeopardy", date(2020, 6, 24), date(2020, 6, 24), "150"],
        ["Jeopardy", date(2020, 6, 25), date(2020, 6, 25), "150"],
        ["Jeopardy", date(2020, 6, 29), date(2020, 6, 29), "150"]],
    3: [["AB Foundation PAC", "Amplify Media", date(2020, 6, 16), date(2020, 6, 22)]],
    4: [["8", "655", "556.75"]],
    5: [["26900215", "WHP", "90725"], ["26902073", "KTVX", "23550"], ["2478034", "KLAS", "102500"],
        ["296434", "WPSG", "14750"], ["295066", "WWJ", "32150"]],
    6: [["70275", "59733.75"]],
}


def answers(folder: Path) -> dict[int, list]:
    """The questions whose forms the agent was given."""
    given = {p.name for p in (folder / DOCUMENTS).glob("*.pdf")}
    return {q["id"]: ANSWERS[q["id"]] for q in QUESTIONS if set(q["forms"]) <= given}


def sample(dataset: Path, exports: Path, n: int) -> None:
    """n forms: the questions' 9, and the rest drawn at random, the same draw each time."""
    asked = {f for q in QUESTIONS for f in q["forms"]}
    rest = sorted(p.name for p in (dataset / DOCUMENTS).glob("*.pdf") if p.name not in asked)
    random.Random(4).shuffle(rest)
    (exports / DOCUMENTS).mkdir(parents=True)
    for name in sorted(asked) + rest[:max(0, n - len(asked))]:
        shutil.copy2(dataset / DOCUMENTS / name, exports / DOCUMENTS / name)


def judge(given: list, expected: list) -> bool:
    """As round 5's, reading a two-digit year as 20yy, since the forms print "06/16/20"."""
    def iso(v):
        return re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b", lambda m: f"20{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}",
                      v) if isinstance(v, str) else v
    return round5.judge([[iso(x) for x in row] if isinstance(row, list) else row for row in given], expected)


# Reading a label, or a value the store holds, as its kind.

DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")
ISO = re.compile(r"\b(\d{4})-(\d\d)-(\d\d)\b")
AMOUNT = re.compile(r"\d{1,3}(,\d{3})+(\.\d{1,2})?|\d+(\.\d{1,2})?")


def as_date(text: str) -> date | None:
    if m := ISO.search(text):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := DATE.search(text):
        mo, d, y = int(m[1]), int(m[2]), int(m[3])
        y += 2000 if y < 100 else 0
    else:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def as_amount(text: str) -> Decimal | None:
    s = text.strip().replace(" ", "")
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").removeprefix("$")
    if not AMOUNT.fullmatch(s):
        return None
    v = Decimal(s.replace(",", ""))
    return -v if negative else v


def as_id(text: str) -> str | None:
    s = re.sub(r"[^0-9a-z]", "", text.lower())
    return s if len(s) >= 3 else None


def as_name(text: str) -> str | None:
    s = re.sub(r"\(\s*\d+\s*\)", " ", text.lower())  # WideOrbit's own IDs: "America First Action (122842)"
    s = re.sub(r"^\s*(pol|poli|iss)\s*/", " ", s)  # a station's category: "POL/AB Foundation PAC"
    s = " ".join(re.findall(r"[a-z0-9]+", s))
    return s if len(s) >= 3 else None


READ = {"date": as_date, "amount": as_amount, "id": as_id, "name": as_name}

OFFICE = re.compile(r"\b(pres|president|gov|governor|sen|senate|senator|con|cong|congress|house|mayor|ag|supreme court|"
                    r"judge|magistrate|sheriff|commissioner|council|attorney|auditor|secretary|treasurer|assessor|"
                    r"clerk|delegate|board)\b")
PARTY = re.compile(r"\b(d|r|i|dem|rep|democrat|republican)\b")
ORGANISATION = re.compile(r"\b(inc|pac|fund|for|committee|comm|action|majority|league|party|forward|association|"
                          r"council|americans?|dscc|dccc|nrcc|nrsc|rga|dga|c/o)\b")


def names_a_candidate(label: str) -> bool:
    """A station's own label for a campaign, by its candidate: "POL/Ben Salango/Governor/WV/Dem",
    "Hagerty, Bill - TN Senate". A committee's name, "Greg Gianforte for Governor-R", is not one."""
    s = re.sub(r"^\s*(pol|poli|iss)\s*/", "", label.lower()).replace("\n", " ")
    if ORGANISATION.search(s.split("/")[0]):
        return False
    if "/" in s and (OFFICE.search(s) or PARTY.search(s)):
        return True
    return bool(re.match(r"^[a-z]+,\s*[a-z]+\s*-", s))


def stored(v_string, v_decimal, v_date, v_instant) -> dict:
    """A value in the store, read as every kind it could be."""
    if v_string is not None:
        return {"name": as_name(v_string), "id": as_id(v_string), "ids": set(re.findall(r"[0-9a-z]+", v_string.lower())),
                "date": {d} if (d := as_date(v_string)) else set(), "amount": as_amount(v_string)}
    if v_decimal is not None:
        return {"amount": v_decimal, "id": str(int(v_decimal)) if v_decimal == int(v_decimal) else None, "ids": set(),
                "date": set(), "name": None}
    if v_date is not None:
        return {"date": {v_date}, "name": None, "id": None, "ids": set(), "amount": None}
    if v_instant is not None:  # midnight where the form was issued: that day, east or west of UTC
        utc = v_instant.astimezone(timezone.utc)
        return {"date": {utc.date(), (utc + timedelta(hours=12)).date()}, "name": None, "id": None, "ids": set(), "amount": None}
    return {"date": set(), "name": None, "id": None, "ids": set(), "amount": None}


def matches(kind: str, label, value: dict) -> bool:
    if kind == "date":
        return label in value["date"]
    if kind == "amount":
        return value["amount"] is not None and value["amount"] == label
    if kind == "id":
        return value["id"] == label or label in value["ids"]
    if value["name"] is None:
        return False
    short, long = sorted((label, value["name"]), key=len)
    # A call sign is three or four letters, and a station's name starts with it: "WSB", "WSB-TV".
    return short == long or (len(short) >= 4 and f" {short} " in f" {long} ") or f" {long} ".startswith(f" {short} ")


def labels() -> dict[str, dict]:
    """Each form's labelled fields, {field: [text, ...]}, and its line items, [{field: text}]."""
    out = {}
    with gzip.open(LABELS, "rt") as f:
        for line in f:
            d = json.loads(line)
            fields, lines = defaultdict(list), []
            for a in d["annotations"]:
                if isinstance(a[0], str):
                    fields[a[0]] += [v[0].strip() for v in a[1]]
                else:
                    lines.append({k: v[0].strip() for k, v in zip(a[0], a[1][0])})
            out[d["filename"]] = {"fields": dict(fields), "lines": lines}
    return out


def text(path: Path) -> str:
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    except Exception:  # noqa: BLE001 - a form pypdf can't parse reads as a scan
        return ""


PERSON = re.compile(r"sales_?person|salesperson|buyer|account_?exec|executive|(^|/|_)ae($|_)|entered_by|contact|"
                    r"representative|(^|/|_)rep($|_)|signer|signature|person|employee")


def report(conn, folder: Path) -> dict:
    """The store against the labels, form by form. `truth` keeps the counts; the misses, which name
    forms, are for checking by hand and stay out of results/."""
    given = sorted((folder / DOCUMENTS).glob("*.pdf"))
    key = labels()
    texts = {p.name: text(p) for p in given}
    scans = {name for name, t in texts.items() if len(t.split()) < 50}

    # Each form's document entities: by its hash, or by a value of a document naming its file.
    by_hash = {hashlib.sha256(p.read_bytes()).hexdigest(): p.name for p in given}
    entities = defaultdict(set)
    for e, h in rows(conn, 'select e, v from current."document/hash"'):
        if h in by_hash:
            entities[by_hash[h]].add(e)
    for e, v in rows(conn, """select c.e, c.v_string from cur c where c.v_string is not null
                              and c.e in (select e from current."document/hash")"""):
        for p in given:
            if p.name in v:
                entities[p.name].add(e)
    dated = {e for (e,) in rows(conn, 'select e from current."document/issued_at"')}
    citing = defaultdict(set)  # document entity -> the transactions citing it
    for tx, doc in rows(conn, 'select e, v from current."core/evidence"'):
        citing[doc].add(tx)
    values = defaultdict(list)  # transaction -> (entity, value) it asserted
    refs = defaultdict(set)  # transaction -> the records its facts point at
    for e, tx, ref, *v in rows(conn, """select f.e, f.tx, f.v_ref, f.v_string, f.v_decimal, f.v_date, f.v_instant
                                        from fact f join attr a on a.id = f.a where f.op and a.ident not like 'fs/%%'
                                        and a.ident not in ('core/evidence', 'core/confidence', 'document/hash')"""):
        if ref is not None:
            refs[tx].add(ref)
        else:
            values[tx].append((e, stored(*v)))
    # A record one form names and another created, such as an advertiser kept once however many
    # forms name it, holds its values on facts citing the first form. A form's facts reach them by ref.
    current = defaultdict(list)
    for e, *v in rows(conn, """select c.e, c.v_string, c.v_decimal, c.v_date, c.v_instant from cur c join attr a on a.id = c.a
                               where c.v_ref is null and a.ident not like 'fs/%%' and a.ident not like 'document/%%'
                               and a.ident not like 'core/%%'"""):
        current[e].append(stored(*v))

    fields, lines, misses = defaultdict(Counter), Counter(), defaultdict(list)
    for p in given:
        name, form = p.name, key.get(p.name, {"fields": {}, "lines": []})
        txs = {tx for d in entities[name] for tx in citing[d]}
        vals = [ev for tx in txs for ev in values[tx]]
        named = [(r, v) for r in {r for tx in txs for r in refs[tx]} for v in current[r]]
        for field, kind in FIELDS.items():
            if not form["fields"].get(field):
                continue
            fields[field]["labelled"] += 1
            candidate = field == "advertiser" and any(names_a_candidate(t) for t in form["fields"][field])
            read = [x for x in (READ[kind](t) for t in form["fields"][field]) if x is not None]
            if not read:
                fields[field]["unusable"] += 1
                continue
            found = any(matches(kind, x, v) for x in read for _, v in vals)
            by_ref = not found and any(matches(kind, x, v) for x in read for _, v in named)
            if candidate:  # recorded or kept out, either follows the rule; counted apart from the mark
                fields[field]["names_a_candidate"] += 1
                fields[field]["names_a_candidate_recorded"] += found or by_ref
                continue
            if found or by_ref:
                fields[field]["found"] += 1
                fields[field]["found_by_ref"] += by_ref
            else:
                misses[field].append(name)
        # A line item is found when one record holds its amount and dates, each record matched once.
        held = defaultdict(list)
        for e, v in vals:
            held[e].append(v)
        free = set(held)
        for item in form["lines"]:
            want = {k: READ[kind](item[k]) for k, kind in LINE.items() if k in item}
            keys = [k for k in ("sub_amount", "program_start_date", "program_end_date") if want.get(k) is not None]
            lines["labelled"] += 1
            if not keys:
                lines["unusable"] += 1
                continue
            hit = next((e for e in sorted(free) if all(any(matches(LINE[k], want[k], v) for v in held[e]) for k in keys)),
                       None)
            if hit is None:
                misses["line"].append(name)
                continue
            free.discard(hit)
            lines["found"] += 1
            if want.get("program_desc") and any(matches("name", want["program_desc"], v) for v in held[hit]):
                lines["found_with_description"] += 1

    emails = {m.group(0).lower() for t in texts.values() for m in round5.EMAIL.finditer(t)}
    phones = {m.group(0) for t in texts.values() for m in round5.PHONE.finditer(t)}
    strings = [(ident, v.lower()) for ident, v in rows(conn, """select a.ident, c.v_string from cur c join attr a on a.id = c.a
                                                               where c.v_string is not null and a.ident not like 'fs/%%'
                                                               and a.ident not in ('document/url', 'document/hash')""")]
    recorded = [n for n in texts if entities[n]]
    return {
        "forms": {"given": len(given), "recorded": len(recorded),
                  "recorded_more_than_once": sum(1 for n in recorded if len(entities[n]) > 1),
                  "dated": sum(1 for n in recorded if entities[n] & dated),
                  "scans": len(scans), "scans_recorded": sum(1 for n in scans if entities[n]),
                  "not_recorded": sorted(set(texts) - set(recorded))},
        "fields": {f: dict(c) for f, c in fields.items()},
        "lines": dict(lines),
        "people": {"emails_on_forms": len(emails), "phones_on_forms": len(phones),
                   "values_holding_an_email": sum(1 for _, v in strings if any(a in v for a in emails)),
                   "values_holding_a_phone": sum(1 for _, v in strings if any(p.lower() in v for p in phones)),
                   "attributes_naming_a_role": dict(Counter(i for i, _ in strings if PERSON.search(i)))},
        "misses": {k: sorted(v) for k, v in misses.items()},
    }


def truth(conn, folder: Path) -> dict:
    """Counts only: forms recorded, labelled fields and line items found, and people in the store."""
    r = report(conn, folder)
    r["forms"].pop("not_recorded")
    r.pop("misses")
    r["people"]["attributes_naming_a_role"] = sum(r["people"]["attributes_naming_a_role"].values())
    def usable(c):
        return c["labelled"] - c.get("unusable", 0) - c.get("names_a_candidate", 0)
    r["marked"] = {f: round(r["fields"][f].get("found", 0) / usable(r["fields"][f]), 3)
                   for f in MARKED if f in r["fields"] and usable(r["fields"][f])}
    usable = r["lines"].get("labelled", 0) - r["lines"].get("unusable", 0)
    r["marked"]["lines"] = round(r["lines"].get("found", 0) / usable, 3) if usable else None
    return r
