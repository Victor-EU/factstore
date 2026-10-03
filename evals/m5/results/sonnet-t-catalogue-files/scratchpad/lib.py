import hashlib,json,csv,re,sys,os,collections as C
import factstore
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-t-ht3vspo0/catalogue/work/exports/'
S=os.path.dirname(os.path.abspath(__file__))+'/'
def doc(path):
    h=hashlib.sha256(open(EX+path,'rb').read()).hexdigest()
    return ['document/hash',h],path
def write(facts,path,conf=None,chunk=3000):
    d,url=doc(path)
    base=[{'e':d,'a':'document/url','v':url}]
    n=0
    for i in range(0,len(facts),chunk):
        f=base+facts[i:i+chunk]+[{'e':'tmp:tx','a':'core/evidence','v':d}]
        if conf is not None: f.append({'e':'tmp:tx','a':'core/confidence','v':str(conf)})
        factstore.transact(f); n+=len(f)
    return n
def look(a,v): return [a,v]
def hubcode(c):
    c=c.strip().upper().replace('-FBA','') if c.upper().endswith('-FBA') else c.strip().upper()
    m=re.fullmatch(r'AH-?([A-Z]{3})-?(\d+)-?([A-Z]{3})',c)
    assert m,c
    return f'AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}'
