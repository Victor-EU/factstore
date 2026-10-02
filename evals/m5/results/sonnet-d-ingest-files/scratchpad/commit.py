import sys,json,factstore
from run import TX
def mat(t):
    out=[]
    for d in t['docs']:
        out.append({'e':['document/hash',d['hash']],'a':'document/url','v':d['url']})
        out.append({'e':'tmp:tx','a':'core/evidence','v':['document/hash',d['hash']]})
    out.append({'e':'tmp:tx','a':'core/confidence','v':t['conf']})
    for e,a,v in t['facts']: out.append({'e':e,'a':a,'v':v})
    return out
if __name__=='__main__':
    mode=sys.argv[1]; start=int(sys.argv[2]) if len(sys.argv)>2 else 0
    n=0
    for i,t in enumerate(TX):
        if i<start: continue
        try:
            r=factstore.transact(mat(t),dry_run=(mode=='dry'))
        except Exception as ex:
            print('FAIL',i,t['note'],repr(ex)[:600]); break
        n+=1
        if i<2 or mode!='dry' and i%50==0: print(i,t['note'],str(r)[:200])
    print('done',n,'of',len(TX))
