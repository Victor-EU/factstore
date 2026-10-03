import json, sys, factstore
TX=json.load(open('tx.json'))
dry = len(sys.argv)>1 and sys.argv[1]=='dry'
done=0; unchanged=0; errs=[]
for i,t in enumerate(TX):
    facts=list(t['facts'])+[{'e':'tmp:tx','a':'core/evidence','v':['document/hash',t['hash']]},
                            {'e':'tmp:tx','a':'core/confidence','v':t['conf']}]
    try:
        r=factstore.transact(facts,dry_run=dry)
        done+=1
        if i<2: print(r)
    except Exception as e:
        errs.append((i,t['url'],repr(e)[:300])); 
        if len(errs)>5: break
print('ok',done,'errors',len(errs))
for e in errs: print(e)
