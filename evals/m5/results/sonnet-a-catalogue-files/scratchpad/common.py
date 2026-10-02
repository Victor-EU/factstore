import hashlib,os,factstore
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-a-jtof532b/catalogue/work/exports/'
def sha(rel): return hashlib.sha256(open(EX+rel,'rb').read()).hexdigest()
def doc_facts(rels):
    return [f for r in rels for f in ({"e":["document/hash",sha(r)],"a":"document/url","v":r},)]
def write(facts, rels, conf=None, dry=False, chunk=4000):
    """facts about entities; each chunk is its own tx stamped with evidence and confidence."""
    res=[]
    for i in range(0,max(len(facts),1),chunk):
        part=facts[i:i+chunk]
        if not part: break
        extra=doc_facts(rels)
        extra+=[{"e":"tmp:tx","a":"core/evidence","v":["document/hash",sha(r)]} for r in rels]
        if conf is not None: extra.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        r=factstore.transact(part+extra,dry_run=dry)
        res.append(r)
    return res
