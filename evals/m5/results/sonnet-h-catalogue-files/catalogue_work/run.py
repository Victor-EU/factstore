import sys,json
sys.argv=[sys.argv[0]]+sys.argv[1:]
exec(open('catalogue_work/build.py').read().split("if __name__")[0])
import factstore
only=sys.argv[1:] 
N=4000
for lab,f in batches:
    if only and not any(lab.startswith(o) for o in only): continue
    meta=[x for x in f if x['e']=='tmp:tx' or (x['a']=='document/url')]
    data=[x for x in f if x not in meta] if len(f)<20000 else [x for x in f if not(x['e']=='tmp:tx' or x['a']=='document/url')]
    created=0
    for i in range(0,len(data),N):
        r=factstore.transact(data[i:i+N]+meta)
        created+=1
    print(lab,len(data),'facts in',created,'txs',flush=True)
