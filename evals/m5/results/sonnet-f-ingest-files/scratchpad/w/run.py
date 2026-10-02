import json, sys, factstore
ev = json.load(open('events.json'))
dry = len(sys.argv) > 1 and sys.argv[1] == 'dry'
n = ok = unchanged = 0
for e in ev:
    for conf, facts in e['groups']:
        n += 1
        try:
            r = factstore.transact(facts, dry_run=dry)
        except Exception as ex:
            print('FAIL', e['t'], e['label'], conf, type(ex).__name__, str(ex)[:400]); sys.exit(1)
        ok += 1
        if dry and n == 1: print(r)
print('done', n, ok)
