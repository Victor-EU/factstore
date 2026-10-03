import pypdf,glob,os,json
out={}
for f in sorted(glob.glob('*.pdf')):
    r=pypdf.PdfReader(f); out[f]="\n".join(p.extract_text() for p in r.pages)
json.dump(out,open(os.environ['S']+'/pdftext.json','w'),ensure_ascii=False)
