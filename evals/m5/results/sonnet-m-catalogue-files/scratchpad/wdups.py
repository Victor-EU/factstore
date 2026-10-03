import json,sys
sys.argv=['x','none']
exec(open('build.py').read().split("# ---------- sources")[0])
out=json.load(open('dups.json'))
g9=[[F(["shopify/customer_id",n],"core/same_as",["shopify/customer_id",o])] for n,o,r in out if 'm' in r]
g7=[[F(["shopify/customer_id",n],"core/same_as",["shopify/customer_id",o])] for n,o,r in out if r==['na']]
write(g9,'shopify/orders.jsonl',0.9); write(g7,'shopify/orders.jsonl',0.7)
