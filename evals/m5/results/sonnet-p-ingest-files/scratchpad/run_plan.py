import factstore, json, sys
from build import *
hs=[(r[0],r[1]) for r in factstore.query('select f.v, h.v from "factory/item_code" f join "sku/hs_code" h using(e)').rows]
run(hs)
from collections import Counter
print(len(TX), Counter(t['label'].split()[0] for t in TX))
print('NOTES'); 
for k,m in LOG: print(' ',k,m)
json.dump(TX,open('tx.json','w'))
