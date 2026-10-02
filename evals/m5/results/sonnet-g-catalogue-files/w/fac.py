import pypdf,glob,re,json,collections as C,os
rows=[]
for f in sorted(glob.glob('exports/supplier_docs/CI-PL*.pdf')):
    t='\n'.join(p.extract_text() for p in pypdf.PdfReader(f).pages)
    L=t.split('\n')
    for i,l in enumerate(L):
        m=re.match(r'^([A-Z]{2}-?\d{3,5}) (.+)$',l)
        if m:
            hs=None
            for j in range(i+1,min(i+4,len(L))):
                h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',L[j])
                if h: hs=h[1];break
            rows.append((os.path.basename(f),m[1],m[2],hs))
print(len(rows))
d=C.defaultdict(lambda:C.defaultdict(set))
for f,c,desc,hs in rows: d[c]['desc'].add(desc); d[c]['hs'].add(hs); d[c]['f'].add(f)
print(len(d))
for c,v in sorted(d.items()): print(c,v['desc'],v['hs'],len(v['f']))
json.dump({c:{'desc':sorted(v['desc']),'hs':sorted(map(str,v['hs']))} for c,v in d.items()},open('w/factory.json','w'))
