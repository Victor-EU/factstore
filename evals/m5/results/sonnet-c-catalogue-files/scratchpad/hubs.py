"""Phase A: SKU hubs and the crosswalk (Shopify, 3PL, Amazon, factory), suppliers, QuickBooks vendors."""
import sys, glob
import pypdf
from common import *

DRY = '--dry' in sys.argv
prod, var = shopify_products()

# ---- Shopify variants -> hubs
hub = {}   # canonical code -> dict
for v in var:
    c = canon(v['sku'])
    assert c not in hub, c
    hub[c] = dict(variant=gid(v['id']), shop_sku=v['sku'], upc=v['barcode'],
                  title=(prod[v['__parentId']]['title'] + ' ' + v['title']).lower(),
                  exact=(v['sku'] == c))
upc2hub = {h['upc']: c for c, h in hub.items()}
assert len(upc2hub) == len(hub)

# ---- 3PL item master: UPC exact
inv = list(csv.DictReader(open(f'{EX}/3pl/inventory_snapshot.csv')))
for r in inv:
    c = upc2hub[r['UPC']]
    assert 'tpl' not in hub[c]
    hub[c]['tpl'] = r['Item Code']
    hub[c]['tpl_client'] = r['Client SKU']
assert all('tpl' in h for h in hub.values())

# ---- Amazon: seller sku -> strip -FBA -> canonical
fi = list(csv.DictReader(open(f'{EX}/amazon/fba_inventory.txt'), delimiter='\t'))
amz_exact, amz_norm = [], []
for r in fi:
    s = r['sku']
    base = re.sub(r'-FBA$', '', s)
    c = canon(base)
    assert c in hub, (s, c)
    assert 'amz' not in hub[c], c
    hub[c]['amz'] = (s, r['fnsku'], r['asin'])
    (amz_exact if s == c else amz_norm).append(c)
# orders must use only these seller skus
am_skus = {r['sku'] for r in csv.DictReader(open(f'{EX}/amazon/all_orders.txt'), delimiter='\t')}
assert am_skus <= {h['amz'][0] for h in hub.values() if 'amz' in h}, am_skus

# ---- factory items (commercial invoices): corroborated by description
SUP = {'MT': 'NBBW', 'HT': 'SZHT', 'LX': 'YWLX', 'MJ': 'FSMJ', 'QS': 'NBQS', 'RF': 'DGRF', 'TY': 'HZTY', 'YD': 'XMYD'}
items = {}
cidocs = []
for f in sorted(glob.glob(f'{EX}/supplier_docs/CI-PL*.pdf')):
    rel = os.path.relpath(f, EX)
    cidocs.append(doc(rel))
    pre = re.search(r'CI-PL_([A-Z]+)', f).group(1)
    L = '\n'.join(p.extract_text() for p in pypdf.PdfReader(f).pages).split('\n')
    for i, l in enumerate(L):
        m = re.match(r'^([A-Z]{0,2}-?\d+) ([a-z].+)$', l)
        if m:
            hs = next(h.group(1) for j in range(i + 1, i + 4) for h in [re.match(r'^(\d{4}\.\d{2}\.\d{4}) ', L[j])] if h)
            key = f'{SUP[pre]}:{m.group(1)}'
            val = (m.group(2).strip(), hs, SUP[pre])
            assert items.setdefault(key, val) == val, key
desc2hub = collections.defaultdict(list)
for c, h in hub.items():
    desc2hub[h['title']].append(c)
unmatched = []
for k, (d, hs, sup) in items.items():
    cs = desc2hub.get(d, [])
    if len(cs) != 1:
        unmatched.append((k, d)); continue
    assert 'fac' not in hub[cs[0]], cs
    hub[cs[0]]['fac'] = (k, hs, sup)
print('factory items', len(items), 'unmatched', unmatched)
print('hubs without factory item', [c for c, h in hub.items() if 'fac' not in h])
for c, h in sorted(hub.items()):
    print(c, h['shop_sku'], h['tpl'], repr(h['tpl_client']), h.get('amz', ('',))[0], h.get('fac', ('',))[0])
if '--dry' in sys.argv and '--table' in sys.argv:
    sys.exit()

shop_docs = [doc('shopify/products.jsonl')]
tpl_docs = [doc('3pl/inventory_snapshot.csv')]
amz_docs = [doc('amazon/fba_inventory.txt')]

# 1. hubs: canonical codes spelt as Shopify has them; exact tier (conf 1)
def hubfacts(c):
    h = hub[c]
    return [{"e": ["sku/code", c], "a": "shopify/variant_id", "v": h['variant']},
            {"e": ["sku/code", c], "a": "shopify/sku", "v": h['shop_sku']},
            {"e": ["sku/code", c], "a": "sku/upc", "v": h['upc']}]
exact = [c for c in hub if hub[c]['exact']]
norm = [c for c in hub if not hub[c]['exact']]
print('shopify exact', len(exact), 'normalized', len(norm), norm)
write([f for c in exact for f in hubfacts(c)], shop_docs, 1, dry=DRY)
write([f for c in norm for f in hubfacts(c)], shop_docs, 0.9, dry=DRY)

# 2. 3PL: UPC is shared exactly (conf 1)
f = []
for c, h in hub.items():
    f.append({"e": ["sku/upc", h['upc']], "a": "tpl/item_code", "v": h['tpl']})
    if h['tpl_client']:
        f.append({"e": ["sku/upc", h['upc']], "a": "tpl/client_sku", "v": h['tpl_client']})
write(f, tpl_docs, 1, dry=DRY)

# 3. Amazon: seller sku equals our code (conf 1) or equals it after dropping -FBA (conf 0.9)
def amzfacts(cs):
    f = []
    for c in cs:
        s, fn, asin = hub[c]['amz']
        f += [{"e": ["sku/code", c], "a": "amazon/seller_sku", "v": s},
              {"e": ["sku/code", c], "a": "amazon/fnsku", "v": fn},
              {"e": ["sku/code", c], "a": "amazon/asin", "v": asin}]
    return f
write(amzfacts(amz_exact), amz_docs, 1, dry=DRY)
write(amzfacts(amz_norm), amz_docs, 0.9, dry=DRY)
print('amazon exact', len(amz_exact), 'normalized', len(amz_norm), 'hubs without amazon', sum(1 for h in hub.values() if 'amz' not in h))

# 4. suppliers
qb = list(csv.DictReader(open(f'{EX}/quickbooks/vendors.csv')))
qb_docs = [doc('quickbooks/vendors.csv')]
codes = set(SUP.values())
vf = []
for r in qb:
    code = r['Email'].split('@')[1].split('.')[0].upper()   # sales@nbbw.example -> NBBW
    if code in codes:
        vf.append({"e": ["supplier/code", code], "a": "quickbooks/vendor_name", "v": r['Vendor']})
    else:
        print('QuickBooks vendor with no supplier code (not a factory):', r['Vendor'])
assert len(vf) == 8
write(vf, qb_docs, 0.9, dry=DRY)
others = [{"e": ["quickbooks/vendor_name", r['Vendor']], "a": "quickbooks/vendor_name", "v": r['Vendor']}
          for r in qb if r['Email'].split('@')[1].split('.')[0].upper() not in codes]
write(others, qb_docs, 1, dry=DRY)

# 5. factory items, supplier and tariff code: no shared code, matched on description (conf 0.7)
f = []
for c, h in hub.items():
    if 'fac' in h:
        k, hs, sup = h['fac']
        f += [{"e": ["sku/code", c], "a": "factory/item_code", "v": k},
              {"e": ["sku/code", c], "a": "sku/supplier", "v": ["supplier/code", sup]},
              {"e": ["sku/code", c], "a": "sku/hs_code", "v": hs}]
write(f, cidocs, 0.7, dry=DRY)
