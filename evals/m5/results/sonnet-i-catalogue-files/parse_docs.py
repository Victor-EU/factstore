import json,re,collections as C
d=json.load(open('w/pdftext.json'))
items=C.defaultdict(lambda:{'desc':set(),'hs':set(),'docs':set()})
for f,t in d.items():
    m=re.search(r'sales@(\w+)\.example',t)
    if not m: continue
    s=m.group(1).upper()
    L=t.split('\n')
    for i,l in enumerate(L):
        # item line followed by chinese line
        if i+1<len(L) and re.search(r'[一-鿿]',L[i+1]) and not re.search(r'[一-鿿]',l):
            m2=re.match(r'^(\S+) (.+?)(?: (\d{4}\.\d{2}\.\d{4}))?$',l)
            if m2 and re.match(r'^[A-Z]*-?\d+$',m2.group(1)):
                k=(s,m2.group(1)); items[k]['desc'].add(m2.group(2)); items[k]['docs'].add(f)
                if m2.group(3): items[k]['hs'].add(m2.group(3))
            # CI line has hs in the next line? 
    for i,l in enumerate(L):
        pass
