import sys; sys.path.insert(0,'.')
from ing import *
dry = '--go' not in sys.argv
P, docs = build()
CAT = ('document/', 'core/', 'fs/', 'factory/', 'sku/')
r = factstore.query('select h.v, f.a from facts f join "core/evidence" ev on ev.e=f.tx join "document/hash" h on h.e=ev.v group by 1,2')
read = collections.defaultdict(set)
for h, a in r.rows:
    if not a.startswith(CAT): read[h].add(a)
done = skipped = 0; skipdocs = set()
for doc, conf, facts in P.txs:
    if doc.hash in read:
        skipdocs.add(doc.hash); continue
    try:
        res = factstore.transact(facts, dry_run=dry)
    except Exception as ex:
        print('FAIL', doc.url, conf, repr(ex)[:400]); print(json.dumps(facts, default=str)[:1500]); sys.exit(1)
    done += 1
print('tx', done, 'skipped docs already read', len(skipdocs), 'dry' if dry else 'WRITTEN')
