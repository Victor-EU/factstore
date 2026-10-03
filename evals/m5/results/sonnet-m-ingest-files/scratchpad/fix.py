import sys; sys.path.insert(0,'.')
from ing import *
P, docs = build()
DYN = ['po/status','po/etd','shipment/status','shipment/etd','shipment/eta','shipment/delivered_at']
# resolve lookups to entity ids
def ent(lk):
    r = factstore.query(f'select e from "{lk[0]}" where v = $1', [lk[1]]) if False else None
ids = {}
for attr in ('po/number','shipment/hbl','shipment/booking_no'):
    for e, v in factstore.query(f'select e, v from "{attr}"').rows:
        ids[(attr, v)] = e
final = {}
for i,(doc, conf, facts) in enumerate(P.txs):
    for f in facts:
        if f['a'] in DYN:
            lk = f['e']; final[(ids[(lk[0], lk[1])], f['a'])] = (f['v'], i, lk)
cur = {}
for a in DYN:
    for e, v in factstore.query(f'select e, v from "{a}"').rows:
        cur[(e, a)] = v
def norm(a, v):
    if a in ('po/etd',): return str(v)
    if a.startswith('shipment/e') or a == 'shipment/delivered_at':
        return datetime.fromisoformat(v).astimezone(timezone.utc) if isinstance(v, str) else v.astimezone(timezone.utc)
    return v
bad = []
for (e, a), (v, i, lk) in final.items():
    c = cur.get((e, a))
    if c is None or norm(a, c) != norm(a, v):
        bad.append((json.dumps(lk), a, v, c, i))
print(len(final), 'bad', len(bad))
for b in bad[:15]: print(b)
if '--go' in sys.argv:
    byi = collections.defaultdict(list)
    for ek, a, v, c, i in bad:
        byi[i].append({'e': json.loads(ek), 'a': a, 'v': v})
    for i in sorted(byi):
        doc, conf, _ = P.txs[i]
        meta = [{'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', doc.hash]},
                {'e': 'tmp:tx', 'a': 'core/confidence', 'v': conf}]
        factstore.transact(meta + byi[i])
    print('fixed', len(bad), 'in', len(byi), 'txs')
