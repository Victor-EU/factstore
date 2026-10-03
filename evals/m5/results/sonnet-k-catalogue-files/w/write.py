import sys
from build import *
import factstore
only=int(sys.argv[1]) if len(sys.argv)>1 else None
n=0;tot=0
for i,(doc,conf,facts) in enumerate(B):
    if only is not None and i>=only: break
    h=sha(doc)
    for j in range(0,len(facts),4000):
        ch=facts[j:j+4000]
        fx=[{'e':['document/hash',h],'a':'document/url','v':doc},{'e':'tmp:tx','a':'core/evidence','v':['document/hash',h]}]
        if conf!=1 or True: fx.append({'e':'tmp:tx','a':'core/confidence','v':str(conf)})
        r=factstore.transact(fx+ch); n+=1
    print(i,doc,conf,len(facts),flush=True)
