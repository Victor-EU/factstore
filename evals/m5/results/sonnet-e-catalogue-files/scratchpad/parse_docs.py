import re,glob,collections,json
pre={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
items=collections.defaultdict(lambda:{'desc':set(),'hs':collections.Counter(),'docs':set()})
bad=[]
for f in sorted(glob.glob('txt/CI-PL_*.txt')):
    t=open(f).read().split('\n')
    code=pre[f.split('_')[1][:2]]
    for i,l in enumerate(t):
        m=re.match(r'^([A-Za-z0-9-]{2,12})\s+([a-z].*)$',l)
        if m and i+2<len(t):
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4})\s',t[i+2])
            if h:
                k=f'{code}:{m.group(1)}'
                items[k]['desc'].add(m.group(2).strip()); items[k]['hs'][h.group(1)]+=1; items[k]['docs'].add(f)
            else: bad.append((f,l))
print(len(items),len(bad)); print(bad[:10])
for k,v in sorted(items.items()):
    print(k,sorted(v['desc']),dict(v['hs']),len(v['docs']))
