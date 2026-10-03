import pypdf,glob,re,collections,json,os
SUP={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
def parse():
    items=collections.defaultdict(lambda: {'desc':set(),'hs':set(),'docs':set()})
    for f in sorted(glob.glob('supplier_docs/*.pdf')):
        b=os.path.basename(f)
        if b.startswith('LCI'): continue
        pre=re.match(r'(?:CI-PL_)?([A-Z]{2})',b)[1]
        lines='\n'.join(p.extract_text() for p in pypdf.PdfReader(f).pages).split('\n')
        for i,l in enumerate(lines):
            m=re.match(r'^([A-Z]{0,3}-?\d{3,5}[A-Z]?)\s+([a-z].*)$',l)
            if m:
                k=(SUP[pre],m[1]); items[k]['desc'].add(m[2]); items[k]['docs'].add(b)
                hs=re.search(r'\b(\d{4}\.\d{2}\.\d{4})\b',' '.join(lines[i:i+3]))
                if hs: items[k]['hs'].add(hs[1])
    return items
if __name__=='__main__':
    it=parse()
    for k,v in sorted(it.items()): print(k,sorted(v['desc']),v['hs'])
    print(len(it))
