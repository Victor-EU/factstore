import hashlib, json, csv, re, os, sys, collections
import factstore

EX = '/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-c-xa8fl84a/catalogue/work/exports'


def doc(rel):
    h = hashlib.sha256(open(os.path.join(EX, rel), 'rb').read()).hexdigest()
    return rel, h


def write(facts, docs=(), conf=None, chunk=4000, dry=False):
    """One transaction per chunk of facts; each carries its evidence and confidence."""
    pre = []
    for rel, h in docs:
        pre.append({"e": ["document/hash", h], "a": "document/url", "v": rel})
        pre.append({"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", h]})
    if conf is not None:
        pre.append({"e": "tmp:tx", "a": "core/confidence", "v": str(conf)})
    n = 0
    for i in range(0, len(facts), chunk):
        factstore.transact(pre + facts[i:i + chunk], dry_run=dry)
        n += 1
    return n


def gid(s):
    return s.rsplit('/', 1)[1]


def canon(sku):
    """Canonical SKU spelling AH-FAM-NNNN-COL from a Shopify-typed one."""
    s = sku.upper()
    m = re.fullmatch(r'AH-?([A-Z]{3})-?(\d+)-?([A-Z]{3})', s)
    assert m, sku
    return f'AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}'


def shopify_products():
    P = [json.loads(l) for l in open(f'{EX}/shopify/products.jsonl')]
    prod = {p['id']: p for p in P if 'sku' not in p}
    var = [p for p in P if 'sku' in p]
    return prod, var


def shopify_orders():
    o, l = [], []
    for line in open(f'{EX}/shopify/orders.jsonl'):
        d = json.loads(line)
        (l if '__parentId' in d else o).append(d)
    return o, l
