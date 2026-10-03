import glob,re,collections,json,os
T=os.environ['TMPDIR']+'/s/'
sup={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
items=collections.defaultdict(lambda: collections.defaultdict(set))
for f in sorted(glob.glob(T+'*.txt')):
    b=os.path.basename(f)
    if b.startswith('LCI'): continue
    pre=b.split('_')[1][:2] if b.startswith('CI-PL') else b[:2]
    s=sup[pre]
    lines=open(f).read().split('\n')
    for i,l in enumerate(lines):
        m=re.match(r'^([A-Z]{2}-?\d{3,5}|\d{3}) ([a-z].+)$',l)
        if m:
            hs=None
            for j in (i+1,i+2):
                if j<len(lines):
                    h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',lines[j])
                    if h: hs=h.group(1)
            code=m.group(1)
            if code[0].isdigit(): pass
            elif '-' in code: code=code.split('-')[1]
            else: code=code[2:]
            k=s+':'+m.group(1) if not m.group(1)[0].isdigit() else s+':'+m.group(1)
            items[k]['desc'].add(m.group(2))
            if hs: items[k]['hs'].add(hs)
            items[k]['f'].add(b)
if __name__=='__main__':
    for k,v in sorted(items.items()): print(k,sorted(v['desc']),sorted(v['hs']),len(v['f']))
    print(len(items))
