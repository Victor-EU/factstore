import json,sys,factstore
plan=json.load(open('plan.json'))
dry='--commit' not in sys.argv
start=int(sys.argv[sys.argv.index('--from')+1]) if '--from' in sys.argv else 0
for i,t in enumerate(plan['txs']):
    if i<start: continue
    d=t['doc']; h=["document/hash",d['hash']]
    facts=[{"e":h,"a":"document/url","v":d['url']},{"e":h,"a":"document/issued_at","v":d['issued']},
           {"e":"tmp:tx","a":"core/evidence","v":h},{"e":"tmp:tx","a":"core/confidence","v":t['conf']}]+t['facts']
    try:
        r=factstore.transact(facts,dry_run=dry)
    except Exception as ex:
        print('FAIL',i,t['note'],type(ex).__name__,str(ex)[:400]); sys.exit(1)
    if i<3 or i%100==0: print(i,t['note'],r)
print('ok',len(plan['txs']),'dry' if dry else 'committed')
