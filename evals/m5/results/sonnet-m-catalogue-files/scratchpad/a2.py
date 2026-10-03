import glob,re,collections as C,json
sup={}
items=C.defaultdict(set)  # (domain,item)->set of (desc,hs)
for f in sorted(glob.glob('txt/*')):
    t=open(f).read()
    if 'COMMERCIAL INVOICE' not in t: continue
    m=re.search(r'Email: sales@(\w+)\.example',t); dom=m.group(1).upper()
    name=t.split('\n')[1]
    sup[dom]=name
    lines=t.split('\n')
    i=0
    while i<len(lines):
        m=re.match(r'^(\S+) (.+)$',lines[i])
        if i+2<len(lines) and re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',lines[i+2]) and not lines[i].startswith(('Item','TOTAL')):
            code=m.group(1); desc=m.group(2); hs=lines[i+2].split()[0]
            items[(dom,code)].add((desc,hs)); i+=3
        else: i+=1
print(sup)
for k,v in sorted(items.items()): print(k,sorted(v))
