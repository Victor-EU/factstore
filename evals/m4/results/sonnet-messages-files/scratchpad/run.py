import sys,json; sys.path.insert(0,'.')
import plan, factstore
dry = sys.argv[1]=='dry'
T=plan.build()
# skip docs already in store (rule 8)
seen={r[0] for r in factstore.query('select v from "document/hash"').rows}
res=[]
for i,t in enumerate(T):
    h,url=t['doc']
    if h in seen and t.get('note','').startswith(('booking','prealert')) is False and False: pass
    facts=[{'e':['document/hash',h],'a':'document/url','v':url},
           {'e':'tmp:tx','a':'core/evidence','v':['document/hash',h]},
           {'e':'tmp:tx','a':'core/confidence','v':t['conf']}]+t['facts']
    try:
        r=factstore.transact(facts,dry_run=dry)
        res.append((i,t['note'][:40],str(r)[:160]))
    except Exception as ex:
        print('ERR',i,t['note'],ex); 
        if not dry: break
print(len(res)); 
for x in res[:3]+res[-3:]: print(x)
