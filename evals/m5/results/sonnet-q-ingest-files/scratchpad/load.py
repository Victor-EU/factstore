"""Stage 1: read every document into a uniform record list (hash, url, issued_at, kind, parsed)."""
import re, glob, os, hashlib, datetime as dt
from zoneinfo import ZoneInfo
import pypdf

ROOT = "/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-q-l0rkspx5/ingest/work/exports"
NY = ZoneInfo("America/New_York")
LA = ZoneInfo("America/Los_Angeles")
CN = dt.timezone(dt.timedelta(hours=8))
MON = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

PORT_TZ = {"CNNGB": CN, "CNYTN": CN, "CNXMN": CN, "CNNSA": CN, "USNYC": NY, "USLAX": LA}
PORT_NAME = {"Ningbo": "CNNGB", "Yantian": "CNYTN", "Xiamen": "CNXMN", "Nansha": "CNNSA",
             "New York/Newark": "USNYC", "Los Angeles": "USLAX"}
NAME2CODE = {"Ningbo Mingtu Housewares": "NBBW", "Shenzhen Hetai Electric Appliance": "SZHT",
             "Dongguan Ruifeng Silicone Products": "DGRF", "Foshan Mingjia Ceramics": "FSMJ",
             "Hangzhou Tianyi Glassware": "HZTY", "Ningbo Qisheng Stainless Steel": "NBQS",
             "Xiamen Yuanda Bamboo Products": "XMYD", "Yiwu Lanxin Textile": "YWLX"}
CHAT_SUPPLIER = {"DGRF": "DGRF", "FSMJ": "FSMJ", "HZTY": "HZTY", "NBBW": "NBBW", "NBQS": "NBQS",
                 "SZHT": "SZHT", "XMYD": "XMYD", "YWLX": "YWLX"}


def local_midnight(d, port):
    """date -> ISO instant at 00:00 local time of the port."""
    tz = PORT_TZ[port]
    return dt.datetime(d.year, d.month, d.day, tzinfo=tz).isoformat()


def num(s):
    return s.replace(",", "")


def pdf_docs():
    out = []
    for f in sorted(glob.glob(ROOT + "/supplier_docs/*.pdf")):
        b = open(f, "rb").read()
        text = "\n".join(p.extract_text() for p in pypdf.PdfReader(f).pages)
        name = os.path.basename(f)
        d = dict(hash=hashlib.sha256(b).hexdigest(), url="supplier_docs/" + name, text=text)
        L = [l.strip() for l in text.split("\n")]
        if name.startswith("CI-PL_"):
            d["kind"] = "ci"; parse_ci(d, L)
        elif name.startswith("LCI-"):
            d["kind"] = "qc"; parse_qc(d, L)
        else:
            d["kind"] = "pi"; parse_pi(d, L)
        out.append(d)
    return out


def d_iso(s):
    return dt.date.fromisoformat(s)


def parse_pi(d, L):
    t = d["text"]
    d["cn"], d["en"], d["addr"] = L[0], L[1], L[2]
    d["pi_no"] = re.search(r"PI No\.: (\S+)", t).group(1)
    d["date"] = d_iso(re.search(r"Date: (\d{4}-\d\d-\d\d)", t).group(1))
    d["po"] = re.search(r"Your PO: (PO-\d{4}-\d{4})", t).group(1)
    d["incoterm"] = "FOB " + re.search(r"Price term: FOB (\w+)", t).group(1)
    d["port"] = PORT_NAME[d["incoterm"][4:]]
    d["pay"] = re.search(r"Payment: (.*)", t).group(1).strip()
    m = re.search(r"about (\w{3}) (\d\d), (\d{4}) \(ETD\)", t)
    d["etd"] = dt.date(int(m.group(3)), MON[m.group(1)], int(m.group(2)))
    ben = re.search(r"Beneficiary: (.*)", t).group(1).strip()
    d["name"] = ben
    d["code"] = NAME2CODE[ben.replace(", Co., Ltd.", "").replace(" Co., Ltd.", "").strip().rstrip(",")]
    d["contact"] = re.search(r"^(.+?) \(signed and stamped\)", t, re.M).group(1)
    items = []
    for i, l in enumerate(L):
        m = re.match(r"^([\d,]+) (\d+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$", l)
        if m:
            code = L[i - 2].split(" ")[0]
            cur = "CNY" if m.group(3) == "RMB" else "USD"
            items.append(dict(item=code, qty=num(m.group(1)), ctns=m.group(2), cur=cur, price=num(m.group(4)),
                              amount=num(m.group(5))))
    d["items"] = items
    d["cur"] = items[0]["cur"]
    d["issued"] = dt.datetime(d["date"].year, d["date"].month, d["date"].day, tzinfo=CN)


def parse_ci(d, L):
    t = d["text"]
    m = re.search(r"Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (PO-\d{4}-\d{4})", t)
    d["inv"], d["date"], d["po"] = m.group(1), d_iso(m.group(2)), m.group(3)
    m = re.search(r"From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)", t)
    d["origin"], d["dest"], d["vessel"], d["container"], d["hbl"] = m.groups()
    rows = []
    for i, l in enumerate(L):
        m = re.match(r"^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$", l)
        if m:
            rows.append(dict(item=L[i - 2].split(" ")[0], hs=m.group(1), qty=num(m.group(2))))
    cartons = {}
    for l in L:
        m = re.match(r"^\d+(?:-\d+)? (\S+) (\d+) (\d+) ([\d,]+) [\d,.]+ \S+ [\d.]+$", l)
        if m:
            cartons[m.group(1)] = m.group(2)
            for r in rows:
                if r["item"] == m.group(1):
                    r["ctns"] = m.group(2); r["pcs_pk"] = num(m.group(4))
    d["rows"] = rows
    d["issued"] = dt.datetime(d["date"].year, d["date"].month, d["date"].day, tzinfo=CN)


def parse_qc(d, L):
    t = d["text"]
    d["report"] = re.search(r"Report No\.: (\S+)", t).group(1)
    d["date"] = d_iso(re.search(r"Inspection date: (\S+)", t).group(1))
    d["po"] = re.search(r"PO No\.: (PO-\d{4}-\d{4})", t).group(1)
    d["result"] = re.search(r"Overall result: (PASS|FAIL)", t).group(1)
    d["sample"] = re.search(r"sample size (\d+)", t).group(1)
    d["inspector"] = "LinkCheck Inspection Services"
    assert L[0] == "LINKCHECK INSPECTION SERVICES"
    d["issued"] = dt.datetime(d["date"].year, d["date"].month, d["date"].day, tzinfo=CN)


def norm_po(tok):
    """Loose PO reference -> PO-YYYY-NNNN."""
    m = re.search(r"(?:(\d{4})-)?(\d{1,4})\s*$", tok)
    year, n = m.group(1), int(m.group(2))
    if not year:
        year = "2025" if n >= 100 else "2026"
    return f"PO-{year}-{n:04d}"


def email_docs():
    raw = open(ROOT + "/email/ops_inbox.mbox", "rb").read()
    parts = re.split(rb"(?m)^(?=From \S+ )", raw)
    import email
    from email import policy
    out = []
    for p in parts:
        if not p.startswith(b"From "):
            continue
        if p.endswith(b"\n\n"):
            p = p[:-1]
        msg = email.message_from_bytes(p.split(b"\n", 1)[1], policy=policy.default)
        mid = msg["Message-ID"].strip().strip("<>")
        body = msg.get_content()
        d = dict(hash=hashlib.sha256(p).hexdigest(), url="mid:" + mid, subject=str(msg["Subject"]),
                 issued=email.utils.parsedate_to_datetime(msg["Date"]), body=body)
        parse_email(d)
        out.append(d)
    return out


def pdate(s):
    m = re.match(r"(\d\d) (\w{3}) (\d{4})", s)
    return dt.date(int(m.group(3)), MON[m.group(2)], int(m.group(1)))


def parse_email(d):
    s, b = d["subject"], d["body"]
    if s.startswith("Booking Confirmation"):
        d["kind"] = "booking"
        d["so"] = re.search(r"^SO: (\S+)", b, re.M).group(1)
        eq = re.search(r"^Equipment: (.*)", b, re.M).group(1)
        d["mode"] = "LCL" if eq.startswith("LCL") else eq.split("x")[1]
        d["vessel"] = re.search(r"^Vessel/Voyage: (.*)", b, re.M).group(1).strip()
        m = re.search(r"POL: .*\((\w+)\)\s+POD: .*\((\w+)\)", b)
        d["origin"], d["dest"] = m.groups()
        d["etd_d"] = pdate(re.search(r"^ETD: (.*)", b, re.M).group(1))
        d["eta_d"] = pdate(re.search(r"^ETA: (.*)", b, re.M).group(1))
        pos = re.search(r"^POs: (.*)", b, re.M).group(1)
        d["pos"] = [norm_po(x) for x in pos.split(",")]
        d["pos_raw"] = pos
    elif s.startswith("RE: Booking Confirmation"):
        d["kind"] = "rolled"
        d["so"] = re.search(r"SO (\S+)", b).group(1)
        m = re.search(r"New ETD (\d\d \w{3} \d{4}), ETA (\d\d \w{3} \d{4})", b)
        d["etd_d"], d["eta_d"] = pdate(m.group(1)), pdate(m.group(2))
    elif s.startswith("Shipping Advice"):
        d["kind"] = "prealert"
        d["hbl"] = re.search(r"^HBL: (\S+)", b, re.M).group(1)
        m = re.search(r"^Container/Seal: (\S+) /", b, re.M)
        d["container"] = m.group(1)
        d["vessel"] = re.search(r"^Vessel/Voyage: (.*)", b, re.M).group(1).strip()
        m = re.search(r"^ATD (.+): (\d\d \w{3} \d{4})", b, re.M)
        d["origin"], d["atd"] = PORT_NAME[m.group(1)], pdate(m.group(2))
        m = re.search(r"^ETA (.+): (\d\d \w{3} \d{4})", b, re.M)
        d["dest"], d["eta_d"] = PORT_NAME[m.group(1)], pdate(m.group(2))
        d["lines"] = [dict(po=m.group(1), item=m.group(2), ctns=m.group(3), qty=m.group(4))
                      for m in re.finditer(r"^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs", b, re.M)]
    elif s.startswith("ETA update"):
        d["kind"] = "eta"
        m = re.search(r"revised ETA (\d\d \w{3} \d{4}) for HBL (\S+)", b)
        d["eta_d"], d["hbl"] = pdate(m.group(1)), m.group(2)
    elif s.startswith("Arrival Notice"):
        d["kind"] = "arrival"
        m = re.search(r"HBL (\S+) \((\S+)\) on (.+?) is arriving (.+?) on (\d\d \w{3} \d{4})", b)
        d["hbl"], d["container"], d["vessel"], d["dest"], d["eta_d"] = (m.group(1), m.group(2), m.group(3),
                                                                           PORT_NAME[m.group(4)], pdate(m.group(5)))
    elif s.startswith("Entry Summary"):
        d["kind"] = "entry"
        d["entry"] = re.search(r"^Entry (\S+) filed for (\S+)\.", b, re.M).group(1)
        d["ref"] = re.search(r"^Entry (\S+) filed for (\S+)\.", b, re.M).group(2)
        g = lambda k: num(re.search(rf"^{k}: USD ([\d,.]+)", b, re.M).group(1))
        d["value"], d["hts"], d["s301"], d["addl"], d["mpf"], d["hmf"], d["total"] = (
            g("Entered value"), g(r"Duty \(HTS\)"), g("Section 301"), g("Additional duties"), g("MPF"), g("HMF"),
            g("Total duties and fees"))
    elif s.startswith("Receipt complete"):
        d["kind"] = "receipt"
        d["ref"] = re.search(r"Receiving complete for (\S+) under (\S+)", b).group(1)
        d["rcv"] = re.search(r"Receiving complete for (\S+) under (\S+)", b).group(2)
        d["discrepancies"] = re.findall(r"^\s+(\S+) \(.*\): expected (\d+), received (\d+), damaged (\d+)", b, re.M)
    else:
        d["kind"] = "unknown"


def chat_docs():
    out = []
    for f in sorted(glob.glob(ROOT + "/wechat/*.txt")):
        name = os.path.basename(f)
        sup = name.split("_")[0]
        t = open(f, encoding="utf8").read()
        blocks = re.split(r"\n\n(?=\d{4}-\d\d-\d\d \d\d:\d\d:\d\d )", t)
        for n, b in enumerate(blocks[1:], 1):
            b = b.rstrip("\n")
            h, _, body = b.partition("\n")
            m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)", h)
            ts = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)
            out.append(dict(kind="chat", hash=hashlib.sha256(b.encode("utf8")).hexdigest(),
                            url=f"wechat/{name}#{n}", issued=ts, sup=sup, sender=m.group(2),
                            ours=m.group(2).startswith("Maya"), text=body, n=n, file=name))
    return out


def load_all():
    docs = pdf_docs() + email_docs() + chat_docs()
    docs.sort(key=lambda d: (d["issued"].astimezone(dt.timezone.utc), d["url"]))
    return docs


if __name__ == "__main__":
    ds = load_all()
    import collections
    print(collections.Counter(d["kind"] for d in ds))
    for d in ds:
        if d["kind"] == "unknown":
            print(d["subject"])
