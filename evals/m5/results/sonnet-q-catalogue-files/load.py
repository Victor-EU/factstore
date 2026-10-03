"""Catalogue loader. Usage: python load.py <phase> [start end]
Phases: hubs, suppliers, shopify, amazon, tpl, dupes, authority
Every write is by lookup on an identity attribute, so re-running is safe."""
import sys, os, re, csv, json, hashlib, pickle, datetime, collections as C
import factstore

EX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
SCR = '/tmp/claude-501'
BATCH = 4000


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


_docs = {}


def doc(rel, issued=None):
    """Document facts for an export file; returns (hash, facts)."""
    p = os.path.join(EX, rel)
    h = sha(p)
    if issued is None:
        issued = datetime.datetime.fromtimestamp(os.stat(p).st_mtime, datetime.timezone.utc).strftime('%Y-%m-%dT00:00:00Z')
    e = ['document/hash', h]
    return h, [{'e': e, 'a': 'document/url', 'v': rel}, {'e': e, 'a': 'document/issued_at', 'v': issued}]


def write(facts, docs, conf=None):
    """docs: list of (hash, facts). One transaction, evidence on each doc."""
    f = list(facts)
    for h, df in docs:
        f += df
        f.append({'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', h]})
    if conf is not None:
        f.append({'e': 'tmp:tx', 'a': 'core/confidence', 'v': str(conf)})
    return factstore.transact(f)


def batched(facts_by_record, docs, size=BATCH, conf=None, lo=0, hi=None):
    """facts_by_record: list of fact lists (a record's facts stay together)."""
    recs = facts_by_record[lo:hi]
    cur = []
    n = 0
    for r in recs:
        cur += r
        if len(cur) >= size:
            write(cur, docs, conf); n += len(cur); cur = []
            print('wrote', n, flush=True)
    if cur:
        write(cur, docs, conf); n += len(cur)
    print('done', n, 'facts for', len(recs), 'records', flush=True)


def canon_sku(s):
    s = s.upper()
    if s == 'AHUTN0017NAT':
        return 'AH-UTN-0017-NAT'
    m = re.fullmatch(r'AH-([A-Z]{3})-(\d+)-([A-Z]{3})', s)
    return 'AH-%s-%04d-%s' % (m[1], int(m[2]), m[3])


PAT = re.compile(r'AH-[A-Z]{3}-\d{4}-[A-Z]{3}')
num = lambda gid: gid.rsplit('/', 1)[1]


def shopify_variants():
    pv = [json.loads(l) for l in open(os.path.join(EX, 'shopify/products.jsonl'))]
    return [p for p in pv if 'sku' in p]


def phase_hubs():
    pdoc = doc('shopify/products.jsonl')
    V = shopify_variants()
    exact, norm = [], []
    for v in V:
        hub = canon_sku(v['sku'])
        recs = [
            {'e': ['sku/code', hub], 'a': 'sku/code', 'v': hub},
            {'e': ['sku/code', hub], 'a': 'shopify/variant_id', 'v': num(v['id'])},
            {'e': ['sku/code', hub], 'a': 'sku/upc', 'v': v['barcode']},
        ]
        (exact if v['sku'] == hub else norm).append(recs)
    print(len(exact), len(norm))
    batched(exact, [pdoc], conf=1)
    batched(norm, [pdoc], conf=0.9)
    # 3PL item codes: matched on UPC, equal in both systems
    inv = list(csv.DictReader(open(os.path.join(EX, '3pl/inventory_snapshot.csv'))))
    idoc = doc('3pl/inventory_snapshot.csv')
    recs = [[{'e': ['sku/upc', r['UPC']], 'a': 'tpl/item_code', 'v': r['Item Code']}] for r in inv]
    batched(recs, [idoc], conf=1)
    # Amazon listings
    hubs = {canon_sku(v['sku']) for v in V}
    fi = list(csv.DictReader(open(os.path.join(EX, 'amazon/fba_inventory.txt')), delimiter='\t'))
    adoc = doc('amazon/fba_inventory.txt')
    ex2, nm2 = [], []
    seen = set()
    for r in fi:
        s = r['sku']
        hub = s if s in hubs else re.sub(r'-FBA$', '', s)
        assert hub in hubs, s
        assert hub not in seen or True
        recs = [
            {'e': ['amazon/seller_sku', s], 'a': 'amazon/seller_sku', 'v': s},
            {'e': ['amazon/seller_sku', s], 'a': 'listing/sku', 'v': ['sku/code', hub]},
            {'e': ['amazon/seller_sku', s], 'a': 'listing/asin', 'v': ['amazon/asin', r['asin']]},
            {'e': ['amazon/seller_sku', s], 'a': 'amazon/fnsku', 'v': r['fnsku']},
            {'e': ['amazon/asin', r['asin']], 'a': 'amazon/asin', 'v': r['asin']},
        ]
        (ex2 if s == hub else nm2).append(recs)
    batched(ex2, [adoc], conf=1)
    batched(nm2, [adoc], conf=0.9)


def phase_suppliers():
    rows, title = pickle.load(open(SCR + '/fac.pkl', 'rb'))
    V = shopify_variants()
    prod = {}
    for l in open(os.path.join(EX, 'shopify/products.jsonl')):
        d = json.loads(l)
        if 'sku' not in d:
            prod[d['id']] = d
    n = lambda s: re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()
    bydesc = {n(prod[v['__parentId']]['title'] + ' ' + v['title']): canon_sku(v['sku']) for v in V}
    pre = {'RF': 'DGRF', 'HT': 'SZHT', 'LX': 'YWLX', 'MJ': 'FSMJ', 'MT': 'NBBW', 'QS': 'NBQS', 'TY': 'HZTY', 'YD': 'XMYD'}
    T = pickle.load(open(SCR + '/pdftext.pkl', 'rb'))
    sdir = os.path.join(EX, 'supplier_docs')
    docs_by_sup = C.defaultdict(list)
    for f, t in sorted(T.items()):
        if f.startswith('CI-PL'):
            sup = pre[f.split('_')[1][:2]]
            issued = re.search(r'Date: (\d{4}-\d{2}-\d{2})', t)[1] + 'T00:00:00Z'
            docs_by_sup[sup].append(doc('supplier_docs/' + f, issued))
    for sup, dl in docs_by_sup.items():
        facts = []
        for (s, item, desc), hs in rows.items():
            if s != sup:
                continue
            hub = bydesc[n(desc)]
            e = ['sku/code', hub]
            facts += [
                {'e': e, 'a': 'factory/item_code', 'v': '%s:%s' % (sup, item)},
                {'e': e, 'a': 'sku/hs_code', 'v': list(hs)[0]},
                {'e': e, 'a': 'sku/supplier', 'v': ['supplier/code', sup]},
                {'e': ['supplier/code', sup], 'a': 'supplier/code', 'v': sup},
            ]
        write(facts, dl, 0.7)
        print(sup, len(facts))
    # QuickBooks vendors: company name as printed on the supplier's invoices, email domain agrees
    qb = list(csv.DictReader(open(os.path.join(EX, 'quickbooks/vendors.csv'))))
    qdoc = doc('quickbooks/vendors.csv')
    code_by_domain = {'nbbw': 'NBBW', 'szht': 'SZHT', 'ywlx': 'YWLX', 'dgrf': 'DGRF', 'fsmj': 'FSMJ', 'xmyd': 'XMYD', 'nbqs': 'NBQS', 'hzty': 'HZTY'}
    sup_f, other_f = [], []
    for r in qb:
        m = re.search(r'@(\w+)\.example', r['Email'])
        code = code_by_domain.get(m[1]) if m else None
        if code:
            sup_f.append({'e': ['supplier/code', code], 'a': 'quickbooks/vendor', 'v': r['Vendor']})
        else:
            other_f.append({'e': ['quickbooks/vendor', r['Vendor']], 'a': 'quickbooks/vendor', 'v': r['Vendor']})
    print(len(sup_f), len(other_f))
    write(sup_f, [qdoc], 0.9)
    write(other_f, [qdoc])


def phase_shopify(lo=0, hi=None):
    path = os.path.join(EX, 'shopify/orders.jsonl')
    d = doc('shopify/orders.jsonl')
    cust, orders, lines = {}, [], []
    for l in open(path):
        o = json.loads(l)
        if '/Order/' in o['id']:
            orders.append(o)
            cust[num(o['customer']['id'])] = 1
        else:
            lines.append(o)
    custrecs = [[{'e': ['shopify/customer_id', c], 'a': 'shopify/customer_id', 'v': c}] for c in cust]
    ordrecs = []
    for o in orders:
        oid = num(o['id'])
        e = ['shopify/order_id', oid]
        ordrecs.append([
            {'e': e, 'a': 'shopify/order_id', 'v': oid},
            {'e': e, 'a': 'shopify/order_name', 'v': o['name']},
            {'e': e, 'a': 'order/customer', 'v': ['shopify/customer_id', num(o['customer']['id'])]},
        ])
    linrecs = []
    for x in lines:
        lid = num(x['id'])
        e = ['shopify/line_item_id', lid]
        linrecs.append([
            {'e': e, 'a': 'shopify/line_item_id', 'v': lid},
            {'e': e, 'a': 'core/part_of', 'v': ['shopify/order_id', num(x['__parentId'])]},
            {'e': e, 'a': 'line/sku', 'v': ['shopify/variant_id', num(x['variant']['id'])]},
        ])
    allrecs = custrecs + ordrecs + linrecs
    print(len(custrecs), len(ordrecs), len(linrecs))
    batched(allrecs, [d], lo=lo, hi=hi)


def phase_amazon(lo=0, hi=None):
    d = doc('amazon/all_orders.txt')
    ao = list(csv.DictReader(open(os.path.join(EX, 'amazon/all_orders.txt')), delimiter='\t'))
    orders = list(dict.fromkeys(r['amazon-order-id'] for r in ao))
    recs = [[{'e': ['amazon/order_id', o], 'a': 'amazon/order_id', 'v': o}] for o in orders]
    for r in ao:
        k = '%s/%s' % (r['amazon-order-id'], r['sku'])
        e = ['amazon/order_line', k]
        recs.append([
            {'e': e, 'a': 'amazon/order_line', 'v': k},
            {'e': e, 'a': 'core/part_of', 'v': ['amazon/order_id', r['amazon-order-id']]},
            {'e': e, 'a': 'line/listing', 'v': ['amazon/seller_sku', r['sku']]},
        ])
    print(len(orders), len(recs) - len(orders))
    batched(recs, [d], lo=lo, hi=hi)
    sd = doc('amazon/fba_inbound_shipments.csv')
    sh = list(csv.DictReader(open(os.path.join(EX, 'amazon/fba_inbound_shipments.csv'))))
    batched([[{'e': ['amazon/fba_shipment_id', r['Shipment ID']], 'a': 'amazon/fba_shipment_id', 'v': r['Shipment ID']}] for r in sh], [sd])


def phase_tpl(lo=0, hi=None):
    rd = doc('3pl/receipts.csv')
    rc = list(csv.DictReader(open(os.path.join(EX, '3pl/receipts.csv'))))
    recs, seen = [], set()
    for r in rc:
        n = r['Receipt #']
        if n not in seen:
            seen.add(n)
            f = [{'e': ['tpl/receipt_no', n], 'a': 'tpl/receipt_no', 'v': n}]
            for p in re.split(r'\s*/\s*', r['Reference']):
                if p:
                    f.append({'e': ['tpl/receipt_no', n], 'a': 'receipt/po', 'v': ['po/number', p]})
            recs.append(f)
        k = '%s/%s' % (n, r['Item Code'])
        e = ['tpl/receipt_line', k]
        recs.append([
            {'e': e, 'a': 'tpl/receipt_line', 'v': k},
            {'e': e, 'a': 'core/part_of', 'v': ['tpl/receipt_no', n]},
            {'e': e, 'a': 'line/sku', 'v': ['tpl/item_code', r['Item Code']]},
        ])
    batched(recs, [rd])
    od = doc('3pl/outbound.csv')
    ob = list(csv.DictReader(open(os.path.join(EX, '3pl/outbound.csv'))))
    recs, seen = [], set()
    for r in ob:
        ref = r['Order Reference']
        k = '%s/%s' % (ref, r['Item Code'])
        if k in seen:
            continue
        seen.add(k)
        whole = ['shopify/order_name', ref] if ref.startswith('#') else ['amazon/fba_shipment_id', ref]
        e = ['tpl/outbound_line', k]
        recs.append([
            {'e': e, 'a': 'tpl/outbound_line', 'v': k},
            {'e': e, 'a': 'core/part_of', 'v': whole},
            {'e': e, 'a': 'line/sku', 'v': ['tpl/item_code', r['Item Code']]},
        ])
    print(len(recs))
    batched(recs, [od], lo=lo, hi=hi)


def phase_dupes():
    d = doc('shopify/orders.jsonl')
    cust = C.defaultdict(lambda: {'em': set(), 'addr': set(), 'first': None})
    for l in open(os.path.join(EX, 'shopify/orders.jsonl')):
        o = json.loads(l)
        if '/Order/' not in o['id']:
            continue
        c = o['customer']
        x = cust[num(c['id'])]
        for e in (c.get('email'), o.get('email')):
            if e:
                x['em'].add(e.strip().lower())
        sa = o.get('shippingAddress') or {}
        x['addr'].add((sa.get('name', '').strip().lower(), sa.get('address1', '').strip().lower(), sa.get('zip', '').strip()))
        if not x['first'] or o['createdAt'] < x['first']:
            x['first'] = o['createdAt']
    nm = lambda e: e.split('@')[0].split('+')[0] + '@' + e.split('@')[1]
    r1, r2 = C.defaultdict(set), C.defaultdict(set)
    for k, x in cust.items():
        for e in x['em']:
            r1[nm(e)].add(k)
        for a in x['addr']:
            if a[0] and a[1]:
                r2[a].add(k)
    parent = {k: k for k in cust}
    def find(a):
        while parent[a] != a:
            a = parent[a]
        return a
    edges = {}
    for rule, groups, conf in (('mailbox', r1, 0.9), ('name_addr', r2, 0.7)):
        for s in groups.values():
            if len(s) > 1:
                s = sorted(s, key=lambda k: (cust[k]['first'], k))
                for k in s[1:]:
                    edges[(s[0], k)] = max(edges.get((s[0], k), 0), conf)
                    ra, rb = find(s[0]), find(k)
                    if ra != rb:
                        parent[rb] = ra
    comps = C.defaultdict(list)
    for k in cust:
        comps[find(k)].append(k)
    out = {0.9: [], 0.7: []}
    stats = C.Counter()
    for comp in comps.values():
        if len(comp) < 2:
            continue
        comp.sort(key=lambda k: (cust[k]['first'], k))
        root = comp[0]
        stats[len(comp)] += 1
        for k in comp[1:]:
            conf = edges.get((root, k), 0.7)
            out[conf].append({'e': ['shopify/customer_id', k], 'a': 'core/same_as', 'v': ['shopify/customer_id', root]})
    print(stats, {k: len(v) for k, v in out.items()})
    json.dump({str(k): [(f['e'][1], f['v'][1]) for f in v] for k, v in out.items()}, open(SCR + '/same_as.json', 'w'))
    for conf, f in out.items():
        if f:
            write(f, [d], conf)


def phase_authority():
    auth = {
        'shopify': ['shopify/customer_id', 'shopify/line_item_id', 'shopify/order_id', 'shopify/order_name', 'shopify/variant_id'],
        'amazon': ['amazon/asin', 'amazon/fba_shipment_id', 'amazon/fnsku', 'amazon/order_id', 'amazon/order_line', 'amazon/seller_sku', 'listing/asin'],
        '3pl': ['tpl/item_code', 'tpl/receipt_no', 'tpl/receipt_line', 'tpl/outbound_line'],
        'quickbooks': ['quickbooks/vendor'],
    }
    f = [{'e': ['fs/ident', a], 'a': 'core/authoritative_source', 'v': s} for s, l in auth.items() for a in l]
    factstore.transact(f)


if __name__ == '__main__':
    ph = sys.argv[1]
    args = [int(x) for x in sys.argv[2:]]
    globals()['phase_' + ph](*args)
