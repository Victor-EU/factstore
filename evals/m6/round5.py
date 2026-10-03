"""Round 5: one mailbox in another industry, with no vocabulary package and no ingestion skill.

One gas trader's mailbox from Enron's West desk (custodian south-s of the EDRM Enron set), June 2000
to April 2001: pipeline notices, deal and invoice queries, nominations, a credit watch list, storage
reports, and personal mail. readpst turns the PST into one file per message. What makes it hard:

- 103 messages in 249 files: the mail client kept most messages in two to four folders, each copy
  a file of its own with its own Message-ID;
- no package: the agent names everything it records, with only the store's tool descriptions;
- real people: senders, recipients, phone numbers and signatures in every message;
- attachments the agent may not be able to read (spreadsheets, Word files, PDFs).

There is no answer key for what the mailbox says. The questions' answers were read from the
messages by hand, and 50 facts drawn from the store are checked against their message by hand.
"""

import email
import hashlib
import re
import shutil
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from email import policy
from pathlib import Path
from urllib.parse import unquote

from score import rows

MAILBOX = "mailbox"


def messages(folder: Path) -> list[dict]:
    out = []
    for path in sorted((folder / MAILBOX).rglob("*.eml")):
        m = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        body = m.get_body(preferencelist=("plain",))
        try:
            text = body.get_content() if body else ""
        except (LookupError, ValueError):
            text = ""
        out.append({"path": path, "id": str(m["Message-ID"] or ""), "subject": str(m["Subject"] or ""),
                    "key": (str(m["Date"]), str(m["Subject"]), hashlib.sha1(text.encode()).hexdigest()),
                    "headers": [str(m[h] or "") for h in ("From", "To", "Cc", "Bcc")], "text": text})
    return out


def distinct(msgs: list[dict]) -> dict[tuple, list[dict]]:
    """Messages by date, subject and body: one message's copies in several folders."""
    out = defaultdict(list)
    for m in msgs:
        out[m["key"]].append(m)
    return out


# Each question names the subject of the message that answers it.
QUESTIONS = (
    {"id": 1, "text": "Which Sitara deal did Barrett's December invoice concern?", "columns": ["deal number"],
     "source": "barrett dec invoice"},
    {"id": 2, "text": "On which deal did Steve South agree with BC Gas, and change it in Sitara, in February 2001?",
     "columns": ["deal number"], "source": "Price Missing"},
    {"id": 3, "text": "What did Crescendo ask to lower its April 2001 nomination to, in MMcf/d?",
     "columns": ["MMcf/d"], "source": "Crescendo April Nom Change"},
    {"id": 4, "text": "Which company did the credit watch list of April 23, 2001 place on No Trades?",
     "columns": ["company"], "source": "Credit Watch List--4/23/01"},
    {"id": 5, "text": "To how much was PG&E Gas Transmission-NW's Kingsgate capacity limited, from which gas day?",
     "columns": ["MMcf/d", "gas day"], "source": "Restriction at Kingsgate"},
    {"id": 6, "text": "On what date does Wild Goose's open season for new storage capacity close?",
     "columns": ["date"], "source": "Wild Goose Storage and the Ruby Pipeline"},
    {"id": 7, "text": "When was Southwest Gas's bid solicitation of April 2001 due?", "columns": ["date"],
     "source": "Bid Solicitation"},
    {"id": 8, "text": "Which Kern River curtailment notice took effect on April 26, 2001, and on what date did it end?",
     "columns": ["notice number", "end date"], "source": "'Critical', Curtailment, 20010426, KRG"},
)

ANSWERS = {
    1: [["516560"]],
    2: [["470448"]],
    3: [["2.84"]],
    4: [["NUI Utilities"]],
    5: [["2220", date(2001, 4, 26)]],
    6: [[date(2001, 5, 22)]],
    7: [[date(2001, 4, 26)]],
    8: [["2001042", date(2001, 4, 29)]],
}


def answers(folder: Path) -> dict[int, list]:
    """The questions whose message the agent was given."""
    subjects = {m["subject"] for m in messages(folder)}
    return {q["id"]: ANSWERS[q["id"]] for q in QUESTIONS if any(q["source"] in s for s in subjects)}


def sample(dataset: Path, exports: Path, n: int) -> None:
    """The messages the questions name and the first n others by date, each with every copy."""
    groups = distinct(messages(dataset))
    asked = {k for k, ms in groups.items() if any(q["source"] in ms[0]["subject"] for q in QUESTIONS)}
    rest = sorted((k for k in groups if k not in asked), key=lambda k: (k[0], k[1]))[:n]
    for k in asked | set(rest):
        for m in groups[k]:
            target = exports / m["path"].relative_to(dataset)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(m["path"], target)


def judge(given: list, expected: list) -> bool:
    """A number is right when the answer holds it, written any way ("2,220 MMcf/d"); a date, when
    the answer gives that day in any common form; a name, when the answer contains it, ignoring
    case and punctuation ("NUI Utilities, Inc." answers "NUI Utilities")."""
    words = lambda v: " ".join(re.findall(r"[a-z0-9.]+", str(v).lower()))

    def numbers(v):
        return {Decimal(x) for x in re.findall(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))}

    def days(v):
        if isinstance(v, date):
            return {v}
        s, out = str(v), set()
        for y, m, d in re.findall(r"(\d{4})-(\d\d)-(\d\d)", s):
            out.add(date(int(y), int(m), int(d)))
        for m, d, y in re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", s):
            out.add(date(int(y), int(m), int(d)))
        for name, d, y in re.findall(r"([A-Z][a-z]+)\.? (\d{1,2}),? (\d{4})", s):
            try:
                out.add(datetime.strptime(f"{name[:3]} {d} {y}", "%b %d %Y").date())
            except ValueError:
                pass
        return out

    def match(g, e):
        if isinstance(e, date):  # a message's "Gas Day 4/26" gives no year
            return e in days(g) or (e.month, e.day) in {(int(m), int(d)) for m, d in
                                                        re.findall(r"^\s*(\d{1,2})/(\d{1,2})\s*$", str(g))}
        if re.fullmatch(r"-?\d+(\.\d+)?", str(e)):  # an ID may be printed with separators: 2001-042
            return Decimal(str(e)) in numbers(g) or re.sub(r"[\s-]", "", str(g)) == str(e)
        return words(e) in words(g)

    if len(given) != len(expected):
        return False
    left = list(given)
    for e in expected:
        hit = next((g for g in left if len(g) == len(e) and all(match(x, y) for x, y in zip(g, e))), None)
        if hit is None:
            return False
        left.remove(hit)
    return True


EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(\.[\w-]+)+")
PHONE = re.compile(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b|\bx\d-\d{4}\b")


def people(msgs: list[dict]) -> tuple[set[str], set[str], set[str]]:
    """The people in the mailbox: names and addresses from the headers, and addresses and phone
    numbers in the bodies."""
    names, addresses, phones = set(), set(), set()
    for m in msgs:
        for h in m["headers"]:
            addresses |= {a.group(0).lower() for a in EMAIL.finditer(h)}
            for part in h.split(","):
                name = " ".join(re.sub(r"<[^>]*>|\(.*?\)|[\"'*]", "", part).split())
                if len(name.split()) >= 2 and "@" not in name:
                    names.add(name.lower())
        addresses |= {a.group(0).lower() for a in EMAIL.finditer(m["text"])}
        phones |= {p.group(0) for p in PHONE.finditer(m["text"])}
    return names, addresses, phones


def truth(conn, folder: Path) -> dict:
    """Counts only. Messages against the documents the store records, and the people in the
    mailbox found in the store."""
    msgs = messages(folder)
    groups = distinct(msgs)
    # A message is recorded when a document names it: by its Message-ID or its file, in any value
    # the document holds (its URL, or an attribute of the agent's own).
    docs = defaultdict(list)
    for e, v in rows(conn, """select d.e, c.v_string from current."document/hash" d
                              join cur c on c.e = d.e where c.v_string is not null"""):
        docs[e].append(v)
    ids = {m["id"].strip("<>"): k for k, ms in groups.items() for m in ms if m["id"].strip("<>")}
    files = {str(m["path"].relative_to(folder / MAILBOX)): k for k, ms in groups.items() for m in ms}

    def names(v):
        v = unquote(v)  # a file:// URL encodes the folders' spaces
        hits = {k for i, k in ids.items() if i in v}
        return hits or {k for f, k in files.items() if v == f or f.endswith("/" + v) or v.endswith("/" + f)}

    named = defaultdict(int)
    for values in docs.values():
        for k in set().union(*(names(v) for v in values)):
            named[k] += 1
    out = {"messages": {"files": len(msgs), "distinct": len(groups),
                        "recorded": len(named), "recorded_more_than_once": sum(1 for v in named.values() if v > 1),
                        "documents": len(docs)}}
    names, addresses, phones = people(msgs)
    stored = [v.lower() for (v,) in rows(conn, """select distinct c.v_string from cur c join attr a on a.id = c.a
                                                   where c.v_string is not null and a.ident not like 'fs/%%'
                                                   and a.ident not in ('document/url', 'document/hash')""")]
    out["people"] = {"names_in_mailbox": len(names), "addresses_in_mailbox": len(addresses), "phones_in_mailbox": len(phones),
                     "values_naming_a_person": sum(1 for v in stored if any(n in v for n in names)),
                     "values_holding_an_address": sum(1 for v in stored if any(a in v for a in addresses)),
                     "values_holding_a_phone": sum(1 for v in stored if any(p.lower() in v for p in phones))}
    out["recorded"] = dict(rows(conn, """select split_part(a.ident, '/', 1), count(*) from cur c join attr a on a.id = c.a
                                         where a.ident not like 'fs/%%' and a.ident not like 'shape/%%'
                                         group by 1 order by 2 desc"""))
    return out


def _has(conn, ident: str) -> bool:
    return bool(rows(conn, "select 1 from attr where ident = %s", ident))
