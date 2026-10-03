import json,csv,re,hashlib,os,sys,collections as C
import factstore
X='exports/'
def sha(p): return hashlib.sha256(open(X+p,'rb').read()).hexdigest()
def doc_facts(p):
    h=sha(p); return h,[{"e":["document/hash",h],"a":"document/url","v":p}]
def write(facts,docs,conf=None,chunk=4000,dry=False):
    """facts: entity-level facts; one tx per chunk, evidence+confidence added."""
    n=0
    ev=[{"e":"tmp:tx","a":"core/evidence","v":["document/hash",h]} for h in docs]
    if conf is not None: ev.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
    for i in range(0,max(len(facts),1),chunk):
        part=facts[i:i+chunk]
        if not part: break
        r=factstore.transact(part+ev,dry_run=dry); n+=len(part)
    return n
def gid(s): return s.rsplit('/',1)[1]
PAT=re.compile(r'^AH-[A-Z]{3}-\d{4}-[A-Z]{3}$')
def canon(s):
    s=s.upper()
    if PAT.match(s): return s
    m=re.match(r'^AH-?([A-Z]{3})-?0*(\d{1,4})-?([A-Z]{3})$',s)
    return f"AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}"
