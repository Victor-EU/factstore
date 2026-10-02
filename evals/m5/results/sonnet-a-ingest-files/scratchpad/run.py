import sys, json
from build import *
dry = '--go' not in sys.argv
have = {r[0] for r in factstore.query('select h.v from "core/evidence" ev join "document/hash" h on h.e = ev.v').rows}
skipped = {}; ok = 0; errs = []
done_log = []
for t in TX:
    h, url = t['doc']
    if h in have:
        skipped[url] = skipped.get(url, 0) + 1; continue
    facts = [dict(e=['document/hash', h], a='document/url', v=url),
             dict(e='tmp:tx', a='core/evidence', v=['document/hash', h]),
             dict(e='tmp:tx', a='core/confidence', v=t['conf'])]
    for f in t['facts']:
        f = dict(f)
        facts.append(f)
    try:
        r = factstore.transact(facts, dry_run=dry)
        if r.errors or r.unknown_attributes: errs.append((url, r.errors, r.unknown_attributes))
        ok += 1; done_log.append((url, r.tx))
    except Exception as ex:
        errs.append((url, repr(ex)[:300])); 
        if not dry: break
print('dry' if dry else 'LIVE', 'ok', ok, 'skipped docs', len(skipped), 'errors', len(errs))
for e in errs[:10]: print(e)
json.dump(done_log, open('done.json', 'w'))
