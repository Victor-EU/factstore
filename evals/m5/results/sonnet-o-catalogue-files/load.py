"""Catalogue loader. Run from ./exports:  python3 ../load.py [part ...] [--dry]
Parts: hubs 3pl_items amazon_listings suppliers factory customers shopify_orders 3pl_lines amazon_orders fba dup
Every write is a lookup on an identity attribute, so a re-run changes nothing."""
import sys, os, csv, json, re, glob, hashlib, datetime, collections
import factstore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DRY = '--dry' in sys.argv
PARTS = [a for a in sys.argv[1:] if not a.startswith('--')]
BATCH = 4000
DOCS = {}


def doc(path):
    if path not in DOCS:
        b = open(path, 'rb').read()
        DOCS[path] = hashlib.sha256(b).hexdigest()
    return DOCS[path]


def doc_facts(path):
    h = doc(path)
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc)
    return [
        {"e": ["document/hash", h], "a": "document/url", "v": path},
        {"e": ["document/hash", h], "a": "document/issued_at", "v": mt.strftime('%Y-%m-%dT%H:%M:%SZ')},
    ]


def tx(facts, docs, conf=None):
    """Write facts in batches, each one transaction citing docs (and a confidence)."""
    if isinstance(docs, str):
        docs = [docs]
    for i in range(0, len(facts), BATCH):
        chunk = list(facts[i:i + BATCH])
        for d in docs:
            chunk += doc_facts(d)
            chunk.append({"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", doc(d)]})
        if conf is not None:
            chunk.append({"e": "tmp:tx", "a": "core/confidence", "v": str(conf)})
        r = factstore.transact(chunk, dry_run=DRY)
        print('  tx', len(chunk), getattr(r, 'tx', None), r if DRY else '', flush=True)


def canon(s):
    s = s.upper().strip()
    if s.endswith('-FBA'):
        s = s[:-4]
    m = re.match(r'^AH-?([A-Z]{3})-?0*(\d+)-?([A-Z]{3})$', s)
    return f'AH-{m[1]}-{int(m[2]):04d}-{m[3]}' if m else None


def last(gid):
    return gid.rsplit('/', 1)[-1]


def products():
    out = []
    for l in open('shopify/products.jsonl'):
        d = json.loads(l)
        if 'sku' in d:
            out.append(d)
    return out


def tsv(p):
    return list(csv.DictReader(open(p), delimiter='\t'))


def want(p):
    return not PARTS or p in PARTS


# ---- hubs: one per Shopify variant, under the canonical spelling of our code
if want('hubs'):
    print('hubs')
    exact, norm = [], []
    for d in products():
        c = canon(d['sku'])
        assert c, d['sku']
        e = ["sku/code", c]
        fs = [{"e": e, "a": "shopify/variant_id", "v": last(d['id'])}]
        if d.get('barcode'):
            fs.append({"e": e, "a": "sku/upc", "v": d['barcode']})
        (exact if c == d['sku'] else norm).append(fs)
    tx([f for fs in exact for f in fs], 'shopify/products.jsonl', 1)
    tx([f for fs in norm for f in fs], 'shopify/products.jsonl', 0.9)

# ---- 3PL item codes, matched to hubs by UPC (exact)
if want('3pl_items'):
    print('3pl_items')
    fs = []
    for r in csv.DictReader(open('3pl/inventory_snapshot.csv')):
        fs.append({"e": ["sku/upc", r['UPC']], "a": "tpl/item_code", "v": r['Item Code']})
    tx(fs, '3pl/inventory_snapshot.csv', 1)

# ---- Amazon listings, ASINs, FNSKUs
if want('amazon_listings'):
    print('amazon_listings')
    orders = tsv('amazon/all_orders.txt')
    inv = tsv('amazon/fba_inventory.txt')
    asin = {}
    for r in orders:
        assert asin.setdefault(r['sku'], r['asin']) == r['asin']
    for r in inv:
        assert asin.setdefault(r['sku'], r['asin']) == r['asin'], r['sku']
    by_asin = collections.defaultdict(set)
    for s, a in asin.items():
        by_asin[a].add(s)
    assert all(len(v) == 1 for v in by_asin.values())
    ex, nm = [], []
    for s, a in sorted(asin.items()):
        c = canon(s)
        assert c
        e = ["amazon/seller_sku", s]
        fs = [{"e": e, "a": "listing/sku", "v": ["sku/code", c]},
              {"e": e, "a": "listing/asin", "v": ["amazon/asin", a]}]
        (ex if c == s else nm).append(fs)
    tx([f for fs in ex for f in fs], ['amazon/all_orders.txt', 'amazon/fba_inventory.txt'], 1)
    tx([f for fs in nm for f in fs], ['amazon/all_orders.txt', 'amazon/fba_inventory.txt'], 0.9)
    tx([{"e": ["amazon/seller_sku", r['sku']], "a": "amazon/fnsku", "v": r['fnsku']} for r in inv],
       'amazon/fba_inventory.txt', 1)

# ---- suppliers, forwarder, broker, 3PL as the vendor list names them
SUP = {'Mingtu Housewares': 'NBBW', 'Hetai Electric (SZ)': 'SZHT', 'Lanxin Textile': 'YWLX',
       'Ruifeng Silicone': 'DGRF', 'Mingjia Ceramics': 'FSMJ', 'Yuanda Bamboo': 'XMYD',
       'Qisheng Stainless': 'NBQS', 'Tianyi Glassware': 'HZTY'}
if want('suppliers'):
    print('suppliers')
    import pypdf
    prefix = {'NBBW': 'MT', 'SZHT': 'HT', 'YWLX': 'LX', 'DGRF': 'RF', 'FSMJ': 'MJ', 'XMYD': 'YD', 'NBQS': 'QS', 'HZTY': 'TY'}
    other, matched = [], []
    for r in csv.DictReader(open('quickbooks/vendors.csv')):
        v = r['Vendor']
        if v in SUP:
            code = SUP[v]
            pi = sorted(glob.glob(f'supplier_docs/{prefix[code]}*.pdf'))[0]
            txt = pypdf.PdfReader(pi).pages[0].extract_text().upper().replace('\n', ' ')
            assert r['Company name'].upper() in txt, (v, pi)
            matched.append({"e": ["supplier/code", code], "a": "quickbooks/vendor", "v": v})
        else:
            other.append({"e": ["quickbooks/vendor", v], "a": "quickbooks/vendor", "v": v})
    tx(matched, 'quickbooks/vendors.csv', 0.9)
    tx(other, 'quickbooks/vendors.csv', 1)

# ---- factory item codes and HS codes, read from the factory's PI / commercial invoice
if want('factory'):
    print('factory')
    from fac import parse
    items = parse()
    parents = {}
    for l in open('shopify/products.jsonl'):
        d = json.loads(l)
        if 'sku' not in d:
            parents[d['id']] = d['title']
    desc2hub = {}
    for l in open('shopify/products.jsonl'):
        d = json.loads(l)
        if 'sku' in d:
            k = (parents[d['__parentId']] + ' ' + d['title']).lower()
            assert k not in desc2hub
            desc2hub[k] = canon(d['sku'])
    used = {}
    per_doc = collections.defaultdict(list)
    for (sup, code), v in sorted(items.items()):
        assert len(v['desc']) == 1 and len(v['hs']) == 1, (sup, code, v)
        desc = next(iter(v['desc']))
        hub = desc2hub.get(desc)
        assert hub, (sup, code, desc)
        assert hub not in used, (hub, code, used[hub])
        used[hub] = code
        ci = sorted(d for d in v['docs'] if d.startswith('CI-PL'))[0]
        e = ["sku/code", hub]
        per_doc['supplier_docs/' + ci] += [
            {"e": e, "a": "factory/item_code", "v": f"{sup}:{code}"},
            {"e": e, "a": "sku/supplier", "v": ["supplier/code", sup]},
            {"e": e, "a": "sku/hs_code", "v": next(iter(v['hs']))}]
    print('  matched', len(used), 'of', len(items), 'items')
    for d, fs in per_doc.items():
        tx(fs, d, 0.7)

# ---- Shopify customers
if want('customers'):
    print('customers')
    ids = set()
    for l in open('shopify/orders.jsonl'):
        d = json.loads(l)
        if '__parentId' not in d:
            ids.add(last(d['customer']['id']))
    tx([{"e": ["shopify/customer_id", i], "a": "shopify/customer_id", "v": i} for i in sorted(ids)],
       'shopify/orders.jsonl', 1)

# ---- Shopify orders and lines
if want('shopify_orders'):
    print('shopify_orders')
    fs = []
    for l in open('shopify/orders.jsonl'):
        d = json.loads(l)
        if '__parentId' in d:
            e = ["shopify/line_item_id", last(d['id'])]
            fs += [{"e": e, "a": "core/part_of", "v": ["shopify/order_id", last(d['__parentId'])]},
                   {"e": e, "a": "line/sku", "v": ["shopify/variant_id", last(d['variant']['id'])]}]
        else:
            e = ["shopify/order_id", last(d['id'])]
            fs += [{"e": e, "a": "shopify/order_name", "v": d['name']},
                   {"e": e, "a": "order/customer", "v": ["shopify/customer_id", last(d['customer']['id'])]}]
    tx(fs, 'shopify/orders.jsonl', 1)

# ---- 3PL receipts and outbound lines
if want('3pl_lines'):
    print('3pl_lines')
    fs, seen = [], set()
    rc = list(csv.DictReader(open('3pl/receipts.csv')))
    pos = collections.defaultdict(set)
    for r in rc:
        for p in r['Reference'].split('/'):
            p = p.strip()
            if p:
                assert re.fullmatch(r'PO-20\d\d-\d{4}', p), p
                pos[r['Receipt #']].add(p)
    for n in sorted({r['Receipt #'] for r in rc}):
        for p in sorted(pos[n]):
            fs.append({"e": ["tpl/receipt_no", n], "a": "receipt/po", "v": ["po/number", p]})
        if not pos[n]:
            fs.append({"e": ["tpl/receipt_no", n], "a": "tpl/receipt_no", "v": n})
    for r in rc:
        k = f"{r['Receipt #']}/{r['Item Code']}"
        assert k not in seen
        seen.add(k)
        e = ["tpl/receipt_line", k]
        fs += [{"e": e, "a": "core/part_of", "v": ["tpl/receipt_no", r['Receipt #']]},
               {"e": e, "a": "line/sku", "v": ["tpl/item_code", r['Item Code']]}]
    tx(fs, '3pl/receipts.csv', 1)
    fs, seen = [], set()
    for r in csv.DictReader(open('3pl/outbound.csv')):
        ref = r['Order Reference']
        k = f"{ref}/{r['Item Code']}"
        assert k not in seen
        seen.add(k)
        whole = ["shopify/order_name", ref] if ref.startswith('#') else ["amazon/fba_shipment_id", ref]
        e = ["tpl/outbound_line", k]
        fs += [{"e": e, "a": "core/part_of", "v": whole},
               {"e": e, "a": "line/sku", "v": ["tpl/item_code", r['Item Code']]}]
    tx(fs, '3pl/outbound.csv', 1)

# ---- FBA inbound shipments
if want('fba'):
    print('fba')
    tx([{"e": ["amazon/fba_shipment_id", r['Shipment ID']], "a": "amazon/fba_shipment_id", "v": r['Shipment ID']}
        for r in csv.DictReader(open('amazon/fba_inbound_shipments.csv'))],
       'amazon/fba_inbound_shipments.csv', 1)

# ---- Amazon orders and lines
if want('amazon_orders'):
    print('amazon_orders')
    fs, seen = [], set()
    for r in tsv('amazon/all_orders.txt'):
        o = r['amazon-order-id']
        assert re.fullmatch(r'\d{3}-\d{7}-\d{7}', o), o
        k = f"{o}/{r['sku']}"
        assert k not in seen
        seen.add(k)
        e = ["amazon/order_line", k]
        fs += [{"e": ["amazon/order_id", o], "a": "amazon/order_id", "v": o},
               {"e": e, "a": "core/part_of", "v": ["amazon/order_id", o]},
               {"e": e, "a": "line/listing", "v": ["amazon/seller_sku", r['sku']]}]
    tx(fs, 'amazon/all_orders.txt', 1)

# ---- duplicate Shopify accounts
if want('dup'):
    print('dup')
    from cust import load
    acc = load()
    byM, byRaw, byA = collections.defaultdict(set), collections.defaultdict(set), collections.defaultdict(set)
    for k, a in acc.items():
        for m in a['mail']:
            byM[m].add(k)
        for m in a['raw']:
            byRaw[m].add(k)
        for x in a['addr']:
            byA[x].add(k)
    conf = {}  # (older, newer) -> best confidence

    def add(group, c):
        g = sorted(group, key=lambda k: (acc[k]['first'], int(k)))
        for n in g[1:]:
            for o in g[:g.index(n)]:
                conf[(o, n)] = max(conf.get((o, n), 0), c)
    for m, v in byRaw.items():
        if len(v) > 1:
            add(v, 1)
    for m, v in byM.items():
        if len(v) > 1:
            add(v, 0.9)
    for x, v in byA.items():
        if len(v) > 1:
            add(v, 0.7)
    best = {}
    for (o, n), c in conf.items():
        if n not in best or (c, -int(o)) > (best[n][1], -int(best[n][0])):
            best[n] = (o, c)
    by_c = collections.defaultdict(list)
    for n, (o, c) in best.items():
        by_c[c].append({"e": ["shopify/customer_id", n], "a": "core/same_as", "v": ["shopify/customer_id", o]})
    for c, fs in sorted(by_c.items()):
        print('  conf', c, len(fs))
        tx(fs, 'shopify/orders.jsonl', c)
