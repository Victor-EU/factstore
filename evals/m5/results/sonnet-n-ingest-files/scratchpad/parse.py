import re, json, hashlib, glob, os, email, email.utils
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

ROOT = "/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-n-a32dezqd/ingest/work/exports"
S = "/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-n-a32dezqd-ingest-work/ef3c4fba-7b6a-491e-b332-88891f220ad2/scratchpad"
SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")
LA = ZoneInfo("America/Los_Angeles")
PORT_TZ = {"CNYTN": SH, "CNNGB": SH, "CNNSA": SH, "CNXMN": SH, "USNYC": NY, "USLAX": LA}
PORT_NAME = {"Yantian": "CNYTN", "Ningbo": "CNNGB", "Nansha": "CNNSA", "Xiamen": "CNXMN",
             "New York/Newark": "USNYC", "Los Angeles": "USLAX"}


def iso(dt):
    return dt.isoformat()


def local_midnight(d, port):
    return datetime(d.year, d.month, d.day, tzinfo=PORT_TZ[port])


def num(s):
    return s.replace(",", "")


# ---------------------------------------------------------------- PDFs
def pdf_docs():
    import pypdf
    out = []
    for f in sorted(glob.glob(ROOT + "/supplier_docs/*.pdf")):
        b = open(f, "rb").read()
        r = pypdf.PdfReader(f)
        t = "\n".join(p.extract_text() for p in r.pages)
        n = os.path.basename(f)[:-4]
        d = {"hash": hashlib.sha256(b).hexdigest(), "url": "supplier_docs/" + os.path.basename(f), "name": n, "text": t}
        if n.startswith("CI-PL_"):
            d["kind"] = "cipl"
            parse_cipl(d)
        elif n.startswith("LCI-"):
            d["kind"] = "qc"
            parse_qc(d)
        else:
            d["kind"] = "pi"
            parse_pi(d)
        out.append(d)
    return out


def parse_pi(d):
    t = d["text"]
    d["pi_no"] = re.search(r"PI No\.: (\S+)", t).group(1)
    ds = re.search(r"Date: (\d{4}-\d{2}-\d{2})", t).group(1)
    d["issued"] = datetime.fromisoformat(ds).replace(tzinfo=SH)
    d["po"] = re.search(r"Your PO: (PO-\d{4}-\d{4})", t).group(1)
    lines = t.split("\n")
    d["name_cn"] = lines[0].strip()
    d["name_caps"] = lines[1].strip()
    d["address"] = lines[2].strip()
    d["beneficiary"] = re.search(r"Beneficiary: (.*)", t).group(1).strip()
    d["incoterm"] = re.search(r"Price term: (.*)", t).group(1).strip()
    d["payment"] = re.search(r"Payment: (.*)", t).group(1).strip()
    m = re.search(r"Delivery: about (\w+ \d+, \d{4}) \(ETD\)", t)
    d["etd"] = datetime.strptime(m.group(1), "%b %d, %Y").date().isoformat()
    cur = None
    rows = []
    # item rows: "<code> <desc>\n<cn>\n<qty> <ctns> <CUR> <price> <CUR> <amount>"
    for m in re.finditer(r"^(\S+) [^\n]*\n[^\n]*\n([\d,]+) ([\d,]+) (USD|RMB) ([\d,]+\.\d+) (?:USD|RMB) ([\d,]+\.\d+)$", t, re.M):
        cur = m.group(4)
        rows.append({"item": m.group(1), "qty": num(m.group(2)), "ctns": num(m.group(3)), "price": num(m.group(5)), "amount": num(m.group(6))})
    d["currency"] = {"RMB": "CNY", "USD": "USD"}[cur]
    d["rows"] = rows
    tot = re.search(r"TOTAL (?:USD|RMB) ([\d,]+\.\d+)", t).group(1)
    d["total"] = num(tot)


def parse_cipl(d):
    t = d["text"]
    m = re.search(r"Invoice No\.: (\S+)\s+Date: (\d{4}-\d{2}-\d{2})\s+Order: (PO-\d{4}-\d{4})", t)
    d["inv_no"], ds, d["po"] = m.group(1), m.group(2), m.group(3)
    d["issued"] = datetime.fromisoformat(ds).replace(tzinfo=SH)
    m = re.search(r"From (\w{5}) to (\w{5}) by sea, (.*?)\s+Container: (\S+)\s+B/L: (\S+)", t)
    d["origin"], d["dest"], d["vessel"], d["container"], d["hbl"] = m.groups()
    rows = []
    for m in re.finditer(r"^(\S+) [^\n]*\n[^\n]*\n(\d{4}\.\d{2}\.\d{4}) ([\d,]+) (?:USD|RMB) ([\d,]+\.\d+) (?:USD|RMB) ([\d,]+\.\d+)$", t, re.M):
        rows.append({"item": m.group(1), "hs": m.group(2), "qty": num(m.group(3)), "price": m.group(4)})
    d["rows"] = rows
    # packing list: "<ctn range> <item> <ctns> <pcs/ctn> <total pcs> <gw> <meas> <cbm>"
    pk = {}
    for m in re.finditer(r"^(\d+-\d+|\d+) (\S+) (\d+) (\d+) ([\d,]+) [\d,]+\.\d [\dx]+ [\d.]+$", t, re.M):
        pk[m.group(2)] = {"ctns": m.group(3), "pcs": num(m.group(5))}
    d["pack"] = pk


def parse_qc(d):
    t = d["text"]
    d["report_no"] = re.search(r"Report No\.: (\S+)", t).group(1)
    ds = re.search(r"Inspection date: (\d{4}-\d{2}-\d{2})", t).group(1)
    d["inspected_on"] = ds
    d["issued"] = datetime.fromisoformat(ds).replace(tzinfo=SH)
    d["po"] = re.search(r"PO No\.: (PO-\d{4}-\d{4})", t).group(1)
    d["result"] = re.search(r"Overall result: (\w+)", t).group(1)
    d["sample"] = re.search(r"sample size (\d+)", t).group(1)
    d["agency"] = t.split("\n")[0].strip().title()
    d["supplier_line"] = re.search(r"Supplier: (.*)", t).group(1)


# ---------------------------------------------------------------- chats
def chat_docs():
    out = []
    for f in sorted(glob.glob(ROOT + "/wechat/*.txt")):
        base = os.path.basename(f)
        code = base.split("_")[0]
        raw = open(f, "rb").read().decode("utf-8")
        lines = raw.split("\n")
        msgs = []
        i = 0
        cur = None
        for ln in lines:
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$", ln)
            if m and (m.group(2).startswith("Maya") or "-" in m.group(2)) and cur is None:
                cur = [ln]
            elif ln.strip() == "":
                if cur:
                    msgs.append(cur)
                    cur = None
            elif cur is not None:
                cur.append(ln)
        if cur:
            msgs.append(cur)
        for n, ml in enumerate(msgs, 1):
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$", ml[0])
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)
            sender = m.group(2)
            text = "\n".join(ml[1:])
            h = hashlib.sha256("\n".join(ml).encode("utf-8")).hexdigest()
            out.append({"kind": "chat", "hash": h, "url": f"wechat/{base}#{n}", "issued": ts, "sender": sender,
                        "text": text, "code": code, "file": base, "n": n, "mine": sender.startswith("Maya")})
    return out


# ---------------------------------------------------------------- email
def email_docs():
    raw = open(ROOT + "/email/ops_inbox.mbox", "rb").read()
    parts = re.split(rb"(?m)^(?=From )", raw)
    out = []
    for p in parts:
        if not p.strip():
            continue
        # strip the blank separator line that frames messages
        b = p.rstrip(b"\n") + b"\n"
        msg = email.message_from_bytes(b.split(b"\n", 1)[1])
        dt = email.utils.parsedate_to_datetime(msg["Date"])
        mid = msg["Message-ID"].strip("<>")
        body = msg.get_payload(decode=True).decode("utf-8")
        out.append({"kind": "email", "hash": hashlib.sha256(b).hexdigest(), "url": "mid:" + mid, "issued": dt,
                    "subject": msg["Subject"], "from": msg["From"], "body": body})
    return out
