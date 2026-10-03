import factstore,hashlib,os,re,json,csv,sys
EX=os.path.abspath('../exports')
def sha(path): return hashlib.sha256(open(path,'rb').read()).hexdigest()
def write(facts,doc,conf=None,chunk=3000,label=''):
    """facts: list of facts; written in chunks, each stamped with evidence doc and confidence."""
    h=sha(os.path.join(EX,doc)); ref=["document/hash",h]
    # group facts by entity so an entity's facts stay in one transaction
    groups=[];cur=[];last=None
    for f in facts:
        key=json.dumps(f['e']) if not isinstance(f['e'],str) else f['e']
        if cur and len(cur)>=chunk and key!=last: groups.append(cur);cur=[]
        cur.append(f); last=key
    if cur: groups.append(cur)
    tot=0
    for g in groups:
        tx=g+[{"e":ref,"a":"document/url","v":doc},{"e":"tmp:tx","a":"core/evidence","v":ref}]
        if conf is not None: tx.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        r=factstore.transact(tx); tot+=len(g)
    print(label or doc,len(facts),'facts in',len(groups),'tx',flush=True)
def code_norm(s):
    s=s.upper(); m=re.fullmatch(r'AH-?([A-Z]{3})-?(\d{1,4})-?([A-Z]{3})',s)
    return f'AH-{m[1]}-{int(m[2]):04d}-{m[3]}' if m else None
