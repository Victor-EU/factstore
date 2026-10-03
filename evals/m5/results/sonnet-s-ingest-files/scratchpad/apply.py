import json, sys, factstore
p = json.load(open('plan.json'))
dry = '--dry' in sys.argv
lim = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else None
done = 0; unchanged = 0
for i, t in enumerate(p['tx'][:lim]):
    facts = list(t['facts']) + [
        {'e': 'tmp:tx', 'a': 'core/evidence', 'v': ['document/hash', t['hash']]},
        {'e': 'tmp:tx', 'a': 'core/confidence', 'v': t['conf']}]
    try:
        r = factstore.transact(facts, dry_run=dry)
    except Exception as ex:
        print('FAIL', i, t['url'], repr(ex)[:600]); sys.exit(1)
    done += 1
print('ok', done, 'last result:', r)
