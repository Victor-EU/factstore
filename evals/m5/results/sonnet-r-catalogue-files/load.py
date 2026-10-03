import csv, json, re, os, sys, hashlib, collections, glob
import factstore

EX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
STAGE = sys.argv[1]
DRY = len(sys.argv) > 2 and sys.argv[2] == 'dry'
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else None
CH = 4000
PAT = re.compile(r'AH-[A-Z]{3}-\d{4}-[A-Z]{3}')
_h = {}


def doc(rel):
    if rel not in _h:
        _h[rel] = hashlib.sha256(open(os.path.join(EX, rel), 'rb').read()).hexdigest()
    h = _h[rel]
    return h, [{"e": ["document/hash", h], "a": "document/url", "v": rel}]


def write(rel, facts, conf=None):
    """facts: list of fact groups (lists) kept whole inside a chunk."""
    h, dfacts = doc(rel)
    ev = [{"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", h]}]
    if conf is not None:
        ev.append({"e": "tmp:tx", "a": "core/confidence", "v": str(conf)})
    chunks, cur, n = [], [], 0
    for g in facts:
        if n + len(g) > CH and cur:
            chunks.append(cur); cur, n = [], 0
        cur += g; n += len(g)
    if cur:
        chunks.append(cur)
    for c in chunks:
        r = factstore.transact(dfacts + ev + c, dry_run=DRY)
        print(rel, STAGE, len(c), 'facts', 'tx', r.tx)


def F(e, a, v):
    return {"e": e, "a": a, "v": v}


def gid(s):
    return s.rsplit('/', 1)[-1]


def canon(sku):
    s = sku.strip().upper()
    if PAT.fullmatch(s):
        return s
    m = re.fullmatch(r'AH-([A-Z]{3})-(\d{1,4})-([A-Z]{3})', s) or re.fullmatch(r'AH([A-Z]{3})(\d{4})([A-Z]{3})', s)
    assert m, sku
    return 'AH-%s-%04d-%s' % (m.group(1), int(m.group(2)), m.group(3))


def products():
    ps = [json.loads(l) for l in open(os.path.join(EX, 'shopify/products.jsonl'))]
    return [p for p in ps if 'ProductVariant' in p['id']]


def hubcode_by_upc():
    return {v['barcode']: canon(v['sku']) for v in products()}


# ---------- stages ----------
if STAGE == 'hubs':
    ex, nm = [], []
    for v in products():
        c = canon(v['sku'])
        g = [F(["sku/code", c], "shopify/variant_id", gid(v['id'])),
             F(["sku/code", c], "sku/upc", v['barcode'])]
        (ex if v['sku'] == c else nm).append(g)
    write('shopify/products.jsonl', ex, 1)
    write('shopify/products.jsonl', nm, 0.9)
    u = hubcode_by_upc()
    inv = list(csv.DictReader(open(os.path.join(EX, '3pl/inventory_snapshot.csv'))))
    write('3pl/inventory_snapshot.csv',
          [[F(["sku/code", u[r['UPC']]], "tpl/item_code", r['Item Code'])] for r in inv], 1)

elif STAGE == 'amazon_listings':
    hubs = set(hubcode_by_upc().values())
    inv = list(csv.DictReader(open(os.path.join(EX, 'amazon/fba_inventory.txt')), delimiter='\t'))
    ex, nm, bad = [], [], []
    for r in inv:
        s = r['sku']
        base = re.sub(r'-FBA$', '', s)
        h = base if base in hubs else None
        if not h:
            bad.append(s); continue
        g = [F(["amazon/seller_sku", s], "listing/sku", ["sku/code", h]),
             F(["amazon/seller_sku", s], "listing/asin", ["amazon/asin", r['asin']]),
             F(["amazon/seller_sku", s], "amazon/fnsku", r['fnsku'])]
        (ex if s == h else nm).append(g)
    print('unmatched', bad)
    write('amazon/fba_inventory.txt', ex, 1)
    write('amazon/fba_inventory.txt', nm, 0.9)

elif STAGE == 'suppliers':
    vend = list(csv.DictReader(open(os.path.join(EX, 'quickbooks/vendors.csv'))))
    exact, other = [], []
    for r in vend:
        m = re.match(r'sales@(\w+)\.example', r['Email'])
        if m and m.group(1).upper() in {'NBBW', 'SZHT', 'YWLX', 'DGRF', 'FSMJ', 'XMYD', 'NBQS', 'HZTY'}:
            exact.append([F(["supplier/code", m.group(1).upper()], "quickbooks/vendor", r['Vendor'])])
        else:
            other.append([F(["quickbooks/vendor", r['Vendor']], "quickbooks/vendor", r['Vendor'])])
    write('quickbooks/vendors.csv', exact, 0.9)
    write('quickbooks/vendors.csv', other)

elif STAGE == 'factory':
    d = json.load(open(os.environ['TMPDIR'] + '/w/pdf.json'))
    prods = [json.loads(l) for l in open(os.path.join(EX, 'shopify/products.jsonl'))]
    P = {p['id']: p for p in prods if 'Product/' in p['id']}
    desc = {}
    for v in prods:
        if 'Variant' in v['id']:
            desc[(P[v['__parentId']]['title'] + ' ' + v['title']).lower()] = canon(v['sku'])
    seen = set()
    for f in sorted(d):
        if not os.path.basename(f).startswith('CI-PL'):
            continue
        t = d[f]
        sup = re.search(r'Email: sales@(\w+)\.example', t).group(1).upper()
        ls = t.split('\n'); grp = []
        for i, l in enumerate(ls):
            m = re.match(r'^(\S+) (.+?)$', l)
            if i + 2 < len(ls) and re.search(r'[一-鿿]', ls[i + 1]) and re.match(r'^\d{4}\.\d{2}\.\d{4} ', ls[i + 2]) and m:
                code = '%s:%s' % (sup, m.group(1))
                if code in seen:
                    continue
                seen.add(code)
                sku = desc[m.group(2).lower()]
                grp.append([F(["sku/code", sku], "factory/item_code", code),
                            F(["sku/code", sku], "sku/hs_code", ls[i + 2].split()[0]),
                            F(["sku/code", sku], "sku/supplier", ["supplier/code", sup])])
        if grp:
            write(f, grp, 0.7)
    print(len(seen))

elif STAGE == 'customers':
    pass  # see shopify stage

elif STAGE == 'shopify':
    orders, lines = [], []
    for l in open(os.path.join(EX, 'shopify/orders.jsonl')):
        d = json.loads(l)
        (orders if '/Order/' in d['id'] else lines).append(d)
    if LIMIT:
        orders = orders[:LIMIT]; ids = {o['id'] for o in orders}; lines = [x for x in lines if x['__parentId'] in ids]
    og = []
    seen_c = set()
    for o in orders:
        oid = gid(o['id']); cid = gid(o['customer']['id'])
        g = [F(["shopify/order_id", oid], "shopify/order_name", o['name']),
             F(["shopify/order_id", oid], "order/customer", ["shopify/customer_id", cid])]
        og.append(g)
    lg = []
    for x in lines:
        lid = gid(x['id']); oid = gid(x['__parentId'])
        lg.append([F(["shopify/line_item_id", lid], "core/part_of", ["shopify/order_id", oid]),
                   F(["shopify/line_item_id", lid], "line/sku", ["sku/code", canon(x['sku'])])])
    write('shopify/orders.jsonl', og)
    write('shopify/orders.jsonl', lg)

elif STAGE == 'dups':
    def norm(e):
        e = e.strip().lower()
        u, dm = e.split('@', 1); u = u.split('+')[0]
        if dm in ('gmail.com', 'googlemail.com'):
            u = u.replace('.', ''); dm = 'gmail.com'
        return u + '@' + dm
    first = {}; mails = collections.defaultdict(set); na = collections.defaultdict(set)
    for l in open(os.path.join(EX, 'shopify/orders.jsonl')):
        d = json.loads(l)
        if '/Order/' not in d['id']:
            continue
        c = d['customer']; k = gid(c['id'])
        first[k] = min(first.get(k, d['createdAt']), d['createdAt'])
        for e in (c['email'], d.get('email')):
            if e: mails[norm(e)].add(k)
        sa = d.get('shippingAddress') or {}
        own = ((c['firstName'] or '') + ' ' + (c['lastName'] or '')).strip().lower()
        if sa.get('name') and sa['name'].strip().lower() == own and sa.get('address1'):
            na[(own, sa['address1'].lower(), sa.get('zip'))].add(k)
    edges = {}
    for rule, m, conf in (('mail', mails, 0.9), ('nameaddr', na, 0.7)):
        for v in m.values():
            v = sorted(v, key=lambda k: (first[k], k))
            for k in v[1:]:
                edges[(v[0], k)] = max(edges.get((v[0], k), 0), conf)
    # clusters with oldest as root
    adj = collections.defaultdict(list)
    for (a, b), c in edges.items():
        adj[a].append((b, c)); adj[b].append((a, c))
    seen = set(); same = []
    for s in sorted(adj, key=lambda k: (first[k], k)):
        if s in seen:
            continue
        comp = []; st = [s]; seen.add(s)
        while st:
            x = st.pop(); comp.append(x)
            for y, c in adj[x]:
                if y not in seen: seen.add(y); st.append(y)
        root = min(comp, key=lambda k: (first[k], k))
        # best bottleneck confidence from root
        best = {root: 1}; todo = [root]
        while todo:
            x = todo.pop()
            for y, c in adj[x]:
                b = min(best[x], c)
                if b > best.get(y, 0): best[y] = b; todo.append(y)
        for k in comp:
            if k != root: same.append((k, root, best[k], len(comp)))
    print(len(same), collections.Counter(c for _, _, c, _ in same), collections.Counter(n for *_, n in same))
    json.dump(same, open(os.environ['TMPDIR'] + '/w/same.json', 'w'))
    for conf in (0.9, 0.7):
        g = [[F(["shopify/customer_id", k], "core/same_as", ["shopify/customer_id", r])] for k, r, c, n in same if c == conf]
        if g and len(sys.argv) > 4 and sys.argv[4] == 'write':
            write('shopify/orders.jsonl', g, conf)

elif STAGE == 'amazon_orders':
    rows = list(csv.DictReader(open(os.path.join(EX, 'amazon/all_orders.txt')), delimiter='\t'))
    if LIMIT: rows = rows[:LIMIT]
    og, seen = [], set()
    for r in rows:
        o = r['amazon-order-id']
        if o not in seen:
            seen.add(o); og.append([F(["amazon/order_id", o], "amazon/order_id", o)])
    lg = []
    for r in rows:
        k = '%s/%s' % (r['amazon-order-id'], r['sku'])
        lg.append([F(["amazon/order_line", k], "core/part_of", ["amazon/order_id", r['amazon-order-id']]),
                   F(["amazon/order_line", k], "line/listing", ["amazon/seller_sku", r['sku']])])
    write('amazon/all_orders.txt', og)
    write('amazon/all_orders.txt', lg)

elif STAGE == 'fba':
    rows = list(csv.DictReader(open(os.path.join(EX, 'amazon/fba_inbound_shipments.csv'))))
    write('amazon/fba_inbound_shipments.csv', [[F(["amazon/fba_shipment_id", r['Shipment ID']], "amazon/fba_shipment_id", r['Shipment ID'])] for r in rows])

elif STAGE == 'tpl':
    u = {r['Item Code']: r['UPC'] for r in csv.DictReader(open(os.path.join(EX, '3pl/inventory_snapshot.csv')))}
    h = hubcode_by_upc()
    sku = lambda ic: ["sku/code", h[u[ic]]]
    rc = list(csv.DictReader(open(os.path.join(EX, '3pl/receipts.csv'))))
    g, seen = [], set()
    for r in rc:
        n = r['Receipt #']
        gg = [F(["tpl/receipt_no", n], "tpl/receipt_no", n)] if n not in seen else []
        if n not in seen:
            for p in re.split(r'\s*/\s*', r['Reference']):
                if p:
                    assert re.fullmatch(r'PO-\d{4}-\d{4}', p), p
                    gg.append(F(["tpl/receipt_no", n], "receipt/po", ["po/number", p]))
        seen.add(n)
        k = '%s/%s' % (n, r['Item Code'])
        gg += [F(["tpl/receipt_line", k], "core/part_of", ["tpl/receipt_no", n]),
               F(["tpl/receipt_line", k], "line/sku", sku(r['Item Code']))]
        g.append(gg)
    write('3pl/receipts.csv', g)
    out = list(csv.DictReader(open(os.path.join(EX, '3pl/outbound.csv'))))
    if LIMIT: out = out[:LIMIT]
    g, seen = [], set()
    for r in out:
        ref = r['Order Reference']
        k = '%s/%s' % (ref, r['Item Code'])
        if k in seen: continue
        seen.add(k)
        whole = ["amazon/fba_shipment_id", ref] if ref.startswith('FBA') else ["shopify/order_name", ref]
        g.append([F(["tpl/outbound_line", k], "core/part_of", whole),
                  F(["tpl/outbound_line", k], "line/sku", sku(r['Item Code']))])
    write('3pl/outbound.csv', g)

elif STAGE == 'authority':
    auth = {'shopify': ['shopify/customer_id', 'shopify/line_item_id', 'shopify/order_id', 'shopify/order_name', 'shopify/variant_id', 'sku/upc', 'sku/title', 'sku/retail_price', 'order/customer'],
            'amazon': ['amazon/asin', 'amazon/fba_line', 'amazon/fba_shipment_id', 'amazon/fnsku', 'amazon/order_id', 'amazon/order_line', 'amazon/seller_sku', 'listing/asin', 'listing/sku'],
            '3pl': ['tpl/item_code', 'tpl/outbound_line', 'tpl/receipt_line', 'tpl/receipt_no'],
            'quickbooks': ['quickbooks/vendor']}
    facts = [F(["fs/ident", a], "core/authoritative_source", s) for s, l in auth.items() for a in l]
    r = factstore.transact(facts, dry_run=DRY); print(r)
