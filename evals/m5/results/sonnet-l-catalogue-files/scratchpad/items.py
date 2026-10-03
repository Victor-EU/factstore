import json,re,os,collections as C
S=os.environ['S']
d=json.load(open(S+'/pdftext.json'))
P=[json.loads(l) for l in open('shopify/products.jsonl')]
parent={p['id']:p for p in P if 'ProductVariant' not in p['id']}
V=[(p['sku'],(parent[p['__parentId']]['title']+' '+p['title']).lower()) for p in P if 'ProductVariant' in p['id']]
sup={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
items={}  # (sup,code)->{desc,hs set,docs}
for f,t in d.items():
    if f.startswith('LCI'):
        # inspection: Supplier name, items
        continue
    pref=re.match(r'(?:CI-PL_)?([A-Z]{2})',f).group(1); s=sup[pref]
    L=t.split('\n')
    for i,l in enumerate(L):
        m=re.match(r'^([A-Z]{0,2}-?\d{3,4}) ([a-z0-9].*)$',l) 
        if m and i+1<len(L) and re.search(r'[一-鿿]',L[i+1]):
            code,desc=m.groups(); 
            hs=None
            nxt=L[i+2] if i+2<len(L) else ''
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',nxt)
            e=items.setdefault((s,code),{'desc':set(),'hs':set(),'docs':set()})
            e['desc'].add(desc); e['docs'].add(f)
            if h: e['hs'].add(h.group(1))
print(len(items))
vm={}
for (s,c),e in sorted(items.items()):
    ds=list(e['desc'])
    hit=[sk for sk,t in V if t==ds[0]]
    print(s,c,ds,sorted(e['hs']),hit, len(e['docs']))
