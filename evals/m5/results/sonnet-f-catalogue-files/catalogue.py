"""Catalogue the exports into the fact store. Usage: python catalogue.py STAGE [--dry] [--limit N]

Stages: hubs, amazon_skus, factory, suppliers, shopify, amazon, fba, tpl, same_as, authority.
"""
import csv, hashlib, json, os, re, sys, glob, collections as C
import factstore

X = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
DRY = '--dry' in sys.argv
LIMIT = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
BATCH = 4000


def sha(path):
    return hashlib.sha256(open(os.path.join(X, path), 'rb').read()).hexdigest()


def commit(facts, docs, conf=None, label=''):
    """Write facts in batches; every batch cites its documents and carries the tier's confidence."""
    ev = []
    for d in docs:
        h = sha(d)
        ev.append({'e': ['document/hash', h], 'a': 'document/url', 'v': d})
        ev.append({'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', h]})
    if conf is not None:
        ev.append({'e': 'tmp:tx', 'a': 'core/confidence', 'v': str(conf)})
    n = 0
    r = None
    for i in range(0, len(facts), BATCH):
        r = factstore.transact(facts[i:i + BATCH] + ev, dry_run=DRY)
        n += 1
    print(f'{label}: {len(facts)} facts in {n} tx{" (dry)" if DRY else ""}; tx={r.tx if r else None} errors={r.errors if r else None}')


def lim(rows):
    return rows[:LIMIT] if LIMIT else rows


def gid(s):
    return s.rsplit('/', 1)[-1]


def canon(sku):
    """Canonical spelling of our SKU: AH-FAM-NNNN-CLR, upper case, four-digit number."""
    s = sku.upper()
    m = re.fullmatch(r'AH-?([A-Z]{3})-?(\d{1,4})-?([A-Z]{3})', s)
    return f'AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}'


def load_products():
    P, V = {}, []
    for l in open(f'{X}/shopify/products.jsonl'):
        d = json.loads(l)
        if '__parentId' in d:
            d['product'] = P[d['__parentId']]
            V.append(d)
        else:
            P[d['id']] = d
    return V


# ---------------------------------------------------------------- stages
def hubs():
    V = load_products()
    inv = list(csv.DictReader(open(f'{X}/3pl/inventory_snapshot.csv')))
    by_upc = {r['UPC']: r['Item Code'] for r in inv}
    docs = ['shopify/products.jsonl', '3pl/inventory_snapshot.csv']
    assert len({v['barcode'] for v in V}) == len(V) == len(inv) and {v['barcode'] for v in V} == set(by_upc)
    f1, f2 = [], []
    for v in V:
        u = v['barcode']
        item = by_upc[u]            # exact: same UPC in both systems
        f1 += [{'e': ['sku/upc', u], 'a': 'sku/upc', 'v': u},
               {'e': ['sku/upc', u], 'a': 'shopify/variant_id', 'v': gid(v['id'])},
               {'e': ['sku/upc', u], 'a': 'tpl/item_code', 'v': item}]
        c = canon(v['sku'])
        (f1 if c == v['sku'] else f2).append({'e': ['sku/upc', u], 'a': 'sku/code', 'v': c})
    commit(f1, docs, 1, 'hubs exact (UPC, variant, 3PL item, identical SKU spelling)')
    commit(f2, docs, 0.9, 'hubs normalized (shop SKU spelling fixed: case, dropped zeros/dashes)')


def amazon_skus():
    inv = list(csv.DictReader(open(f'{X}/amazon/fba_inventory.txt'), delimiter='\t'))
    docs = ['amazon/fba_inventory.txt']
    exact, norm = [], []
    for r in inv:
        s = r['sku']
        hub = re.sub(r'-FBA$', '', s)
        tgt = exact if hub == s else norm
        e = ['sku/code', hub]
        tgt += [{'e': e, 'a': 'amazon/seller_sku', 'v': s},
                {'e': e, 'a': 'amazon/asin', 'v': r['asin']},
                {'e': e, 'a': 'amazon/fnsku', 'v': r['fnsku']}]
    commit(exact, docs, 1, 'amazon exact')
    commit(norm, docs, 0.9, 'amazon -FBA suffix dropped')


SUP = {'MT': 'NBBW', 'HT': 'SZHT', 'LX': 'YWLX', 'MJ': 'FSMJ', 'QS': 'NBQS', 'RF': 'DGRF', 'TY': 'HZTY', 'YD': 'XMYD'}


def factory():
    import pypdf
    V = load_products()
    title = {(v['product']['title'] + ' ' + v['title']).lower(): canon(v['sku']) for v in V}
    facts, docs, seen = [], [], {}
    for p in sorted(glob.glob(f'{X}/supplier_docs/CI-PL_*.pdf')):
        f = os.path.basename(p)
        sup = SUP[f.split('_')[1][:2]]
        docs.append('supplier_docs/' + f)
        L = '\n'.join(x.extract_text() for x in pypdf.PdfReader(p).pages).split('\n')
        for i, l in enumerate(L):
            h = re.match(r'^(\d{4}\.\d\d\.\d{4}) ', l)
            if not h:
                continue
            it, desc = re.match(r'^(\S+) (.+)$', L[i - 2]).groups()
            hub = title[desc.strip().lower()]       # description equals the shop's title + variant
            row = (f'{sup}:{it}', h.group(1), sup)
            assert seen.setdefault(hub, row) == row, (hub, row, seen[hub])
    assert len(seen) == 49 and len({r[0] for r in seen.values()}) == 49
    for hub, (code, hs, sup) in seen.items():
        e = ['sku/code', hub]
        facts += [{'e': e, 'a': 'factory/item_code', 'v': code}, {'e': e, 'a': 'sku/hs_code', 'v': hs},
                  {'e': e, 'a': 'sku/supplier', 'v': ['supplier/code', sup]},
                  {'e': ['supplier/code', sup], 'a': 'supplier/code', 'v': sup}]
    commit(facts, docs, 0.7, 'factory codes, HS, supplier (description match)')


def suppliers():
    rows = list(csv.DictReader(open(f'{X}/quickbooks/vendors.csv')))
    docs = ['quickbooks/vendors.csv']
    codes = set(SUP.values())
    mapped, own = [], []
    for r in rows:
        dom = r['Email'].split('@')[1].split('.')[0].upper()
        if dom in codes:
            mapped += [{'e': ['supplier/code', dom], 'a': 'quickbooks/vendor', 'v': r['Vendor']}]
        else:
            own += [{'e': ['quickbooks/vendor', r['Vendor']], 'a': 'quickbooks/vendor', 'v': r['Vendor']}]
    assert len(mapped) == 8, mapped
    commit(mapped, docs, 0.9, 'quickbooks vendor -> supplier (mailbox domain = supplier code; name checked)')
    commit(own, docs, None, 'quickbooks vendors that are forwarders/brokers/3PL')


def shopify():
    docs = ['shopify/orders.jsonl', 'shopify/products.jsonl']
    V = {gid(v['id']) for v in load_products()}
    orders, lines = [], []
    for l in open(f'{X}/shopify/orders.jsonl'):
        d = json.loads(l)
        (lines if '__parentId' in d else orders).append(d)
    if LIMIT:
        orders = orders[:LIMIT]
        keep = {o['id'] for o in orders}
        lines = [x for x in lines if x['__parentId'] in keep]
    cf = {}
    for o in orders:
        c = gid(o['customer']['id'])
        cf[c] = {'e': ['shopify/customer_id', c], 'a': 'shopify/customer_id', 'v': c}
    commit(list(cf.values()), docs, None, 'shopify customers')
    of = []
    for o in orders:
        e = ['shopify/order_name', o['name']]       # the 3PL's outbound lines may have created it by name
        of += [{'e': e, 'a': 'shopify/order_name', 'v': o['name']},
               {'e': e, 'a': 'shopify/order_id', 'v': gid(o['id'])},
               {'e': e, 'a': 'order/customer', 'v': ['shopify/customer_id', gid(o['customer']['id'])]}]
    commit(of, docs, None, 'shopify orders')
    lf = []
    for x in lines:
        assert gid(x['variant']['id']) in V
        e = ['shopify/line_item_id', gid(x['id'])]
        lf += [{'e': e, 'a': 'shopify/line_item_id', 'v': gid(x['id'])},
               {'e': e, 'a': 'core/part_of', 'v': ['shopify/order_id', gid(x['__parentId'])]},
               {'e': e, 'a': 'line/sku', 'v': ['shopify/variant_id', gid(x['variant']['id'])]}]
    commit(lf, docs, None, 'shopify lines')


def amazon():
    docs = ['amazon/all_orders.txt']
    rows = lim(list(csv.DictReader(open(f'{X}/amazon/all_orders.txt'), delimiter='\t')))
    of, lf, seen = [], [], set()
    for r in rows:
        o = r['amazon-order-id']
        assert re.fullmatch(r'\d{3}-\d{7}-\d{7}', o)
        if o not in seen:
            seen.add(o)
            of.append({'e': ['amazon/order_id', o], 'a': 'amazon/order_id', 'v': o})
        k = f"{o}/{r['sku']}"
        e = ['amazon/order_line', k]
        lf += [{'e': e, 'a': 'amazon/order_line', 'v': k},
               {'e': e, 'a': 'core/part_of', 'v': ['amazon/order_id', o]},
               {'e': e, 'a': 'line/sku', 'v': ['amazon/seller_sku', r['sku']]}]
    commit(of, docs, None, 'amazon orders')
    commit(lf, docs, None, 'amazon order lines')


def fba():
    rows = list(csv.DictReader(open(f'{X}/amazon/fba_inbound_shipments.csv')))
    commit([{'e': ['amazon/fba_shipment_id', r['Shipment ID']], 'a': 'amazon/fba_shipment_id', 'v': r['Shipment ID']}
            for r in rows], ['amazon/fba_inbound_shipments.csv'], None, 'fba shipments')


def tpl():
    rc = list(csv.DictReader(open(f'{X}/3pl/receipts.csv')))
    ob = lim(list(csv.DictReader(open(f'{X}/3pl/outbound.csv'))))
    rf, seen = [], set()
    for r in rc:
        n = r['Receipt #']
        if n not in seen:
            seen.add(n)
            e = ['tpl/receipt_no', n]
            rf.append({'e': e, 'a': 'tpl/receipt_no', 'v': n})
            for po in [p.strip() for p in r['Reference'].split('/') if p.strip()]:
                assert re.fullmatch(r'PO-\d{4}-\d{4}', po), po
                rf.append({'e': e, 'a': 'receipt/po', 'v': ['po/number', po]})
        k = f"{n}/{r['Item Code']}"
        e = ['tpl/receipt_line', k]
        rf += [{'e': e, 'a': 'tpl/receipt_line', 'v': k},
               {'e': e, 'a': 'core/part_of', 'v': ['tpl/receipt_no', n]},
               {'e': e, 'a': 'line/sku', 'v': ['tpl/item_code', r['Item Code']]}]
    commit(rf, ['3pl/receipts.csv'], None, 'tpl receipts')
    of = []
    for r in ob:
        ref = r['Order Reference']
        whole = ['shopify/order_name', ref] if ref.startswith('#') else ['amazon/fba_shipment_id', ref]
        k = f"{ref}/{r['Item Code']}"
        e = ['tpl/outbound_line', k]
        of += [{'e': e, 'a': 'tpl/outbound_line', 'v': k},
               {'e': e, 'a': 'core/part_of', 'v': whole},
               {'e': e, 'a': 'line/sku', 'v': ['tpl/item_code', r['Item Code']]}]
    commit(of, ['3pl/outbound.csv'], None, 'tpl outbound lines')


def norm_mail(e):
    loc, _, dom = e.strip().lower().partition('@')
    loc = loc.split('+')[0]
    if dom in ('gmail.com', 'googlemail.com'):
        loc = loc.replace('.', '')
    return f'{loc}@{dom}'


def load_customers():
    cust = {}
    for l in open(f'{X}/shopify/orders.jsonl'):
        d = json.loads(l)
        if '__parentId' in d:
            continue
        c = d['customer']
        x = cust.setdefault(gid(c['id']), {'mail': norm_mail(c['email']), 'names': set(), 'addr': set(), 'first': '9'})
        x['names'].add(f"{c['firstName']} {c['lastName']}".strip().lower())
        a = d['shippingAddress'] or {}
        x['addr'].add('|'.join((a.get(k) or '').strip().lower() for k in ('address1', 'city', 'provinceCode', 'zip')))
        x['first'] = min(x['first'], d['createdAt'])
    return cust


def same_as_pairs():
    cust = load_customers()
    byA, byB = C.defaultdict(list), C.defaultdict(list)
    for k, x in cust.items():
        byA[x['mail']].append(k)
        for n in x['names']:
            for ad in x['addr']:
                byB[(n, ad)].append(k)
    A, B = [], []                       # rule A: same normalized mailbox and name; rule B: same name and address
    for ks in byA.values():
        A += [(a, b) for a in ks for b in ks if a < b and cust[a]['names'] & cust[b]['names']]
    for ks in byB.values():
        B += [(a, b) for a in ks for b in ks if a < b]

    def uf(edges):
        p = {}

        def f(a):
            p.setdefault(a, a)
            while p[a] != a:
                p[a] = p[p[a]]
                a = p[a]
            return a
        for a, b in edges:
            p[f(a)] = f(b)
        return f
    fA, fAll = uf(A), uf(A + B)
    groups = C.defaultdict(list)
    for k in cust:
        groups[fAll(k)].append(k)
    out = {0.9: [], 0.7: []}
    for g in groups.values():
        if len(g) > 1:
            root = min(g, key=lambda k: (cust[k]['first'], k))      # the earliest account survives
            for k in g:
                if k != root:
                    out[0.9 if fA(k) == fA(root) else 0.7].append((k, root))
    return out, cust


def same_as():
    out, _ = same_as_pairs()
    for conf, pairs in out.items():
        facts = [{'e': ['shopify/customer_id', a], 'a': 'core/same_as', 'v': ['shopify/customer_id', b]} for a, b in pairs]
        commit(facts, ['shopify/orders.jsonl'], conf, f'same_as {conf}')


def authority():
    spec = {'shopify': ['shopify/customer_id', 'shopify/line_item_id', 'shopify/order_id', 'shopify/order_name', 'shopify/variant_id'],
            'amazon': ['amazon/asin', 'amazon/fnsku', 'amazon/order_id', 'amazon/order_line', 'amazon/seller_sku', 'amazon/fba_shipment_id'],
            '3pl': ['tpl/item_code', 'tpl/outbound_line', 'tpl/receipt_line', 'tpl/receipt_no'],
            'quickbooks': ['quickbooks/vendor']}
    facts = [{'e': ['fs/ident', a], 'a': 'core/authoritative_source', 'v': s} for s, al in spec.items() for a in al]
    commit(facts, [], None, 'authority')


STAGES = dict(hubs=hubs, amazon_skus=amazon_skus, factory=factory, suppliers=suppliers, shopify=shopify,
              amazon=amazon, fba=fba, tpl=tpl, same_as=same_as, authority=authority)
if __name__ == '__main__':
    STAGES[sys.argv[1]]()
