import re,glob,collections,json,os
S='/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m4-catalogue-v23fb7l9-work/88818ec5-fe93-4e05-84ff-935035c0b64f/scratchpad'
SUP={'NINGBO MINGTU':'NBBW','SHENZHEN HETAI':'SZHT','YIWU LANXIN':'YWLX','DONGGUAN RUIFENG':'DGRF','FOSHAN MINGJIA':'FSMJ','XIAMEN YUANDA':'XMYD','NINGBO QISHENG':'NBQS','HANGZHOU TIANYI':'HZTY'}
def parse():
    items=collections.defaultdict(lambda: collections.defaultdict(set))
    for f in sorted(glob.glob(S+'/txt/*.txt')):
        b=os.path.basename(f)[:-4]
        if b.startswith('LCI'): continue
        t=open(f).read(); L=t.split('\n')
        sup=next((v for k,v in SUP.items() if k in t.upper()),None)
        assert sup,b
        for i,l in enumerate(L):
            m=re.match(r'^((?:[A-Z]{2}-?)?\d{3,4}) ([a-z].*)$',l)
            if m:
                k=(sup,m.group(1)); items[k]['desc'].add(m.group(2).strip()); items[k]['doc'].add(b)
                for x in L[i+1:i+3]:
                    h=re.match(r'^(\d{4}\.\d\d\.\d{4}) ',x)
                    if h: items[k]['hs'].add(h.group(1))
    return items
if __name__=='__main__':
    it=parse(); print(len(it))
    for k,v in sorted(it.items()): print(k,sorted(v['desc']),sorted(v['hs']),len(v['doc']))
