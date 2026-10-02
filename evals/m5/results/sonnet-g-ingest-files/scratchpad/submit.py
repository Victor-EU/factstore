import sys
from run import *
dry = '--go' not in sys.argv
fails = 0; n = 0; created = 0
for t in TX:
    facts = t['facts'] + [A('tmp:tx', 'core/evidence', ['document/hash', t['doc']['hash']]),
                          A('tmp:tx', 'core/confidence', t['conf'])]
    try:
        r = factstore.transact(facts, dry_run=dry)
        n += 1
    except Exception as ex:
        fails += 1
        print('FAIL', t['doc']['url'], t['topic'], str(ex)[:300])
        if fails > 5: break
print('done', n, 'fails', fails, 'dry', dry)
