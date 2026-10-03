import json,sys,factstore
T=json.load(open('tx.json'))
dry=sys.argv[1]=='dry'
def facts_of(t):
    d=t['doc']; h=['document/hash',d['hash']]
    fs=[dict(e=h,a='document/url',v=d['url']),dict(e=h,a='document/issued_at',v=d['issued']),
        dict(e='tmp:tx',a='core/evidence',v=h),dict(e='tmp:tx',a='core/confidence',v=t['conf'])]
    return fs+t['facts']
bad=0;n=0;txids=[]
for i,t in enumerate(T):
    r=factstore.transact(facts_of(t),dry_run=dry)
    if r.errors or r.unknown_attributes:
        bad+=1; print(i,t['doc']['url'],r.errors,r.unknown_attributes); 
        if not dry: break
    txids.append(r.tx)
print('done',len(T),'bad',bad)
