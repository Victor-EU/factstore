"""Phase B: Shopify, Amazon and 3PL records and their joins."""
import sys
from common import *

DRY = '--dry' in sys.argv
LIMIT = None
prod, var = shopify_products()
vid2sku = {gid(v['id']): canon(v['sku']) for v in var}
orders, lines = shopify_orders()

# ---- Shopify customers, orders, lines
sd = [doc('shopify/orders.jsonl')]
cust = {}
for o in orders:
    c = o['customer']
    cust[gid(c['id'])] = (c['email'], c['firstName'].lower(), c['lastName'].lower())

f = [{"e": ["shopify/customer_id", c], "a": "shopify/customer_id", "v": c} for c in cust]
write(f, sd, 1, dry=DRY)
print('customers', len(cust))

f = []
for o in orders:
    oid = gid(o['id'])
    f += [{"e": ["shopify/order_id", oid], "a": "shopify/order_id", "v": oid},
          {"e": ["shopify/order_id", oid], "a": "shopify/order_name", "v": o['name']},
          {"e": ["shopify/order_id", oid], "a": "order/customer", "v": ["shopify/customer_id", gid(o['customer']['id'])]}]
write(f, sd, 1, dry=DRY)
print('orders', len(orders))

f = []
for l in lines:
    lid = gid(l['id'])
    sku = vid2sku[gid(l['variant']['id'])]
    assert canon(l['sku']) == sku
    f += [{"e": ["shopify/line_item_id", lid], "a": "shopify/line_item_id", "v": lid},
          {"e": ["shopify/line_item_id", lid], "a": "core/part_of", "v": ["shopify/order_id", gid(l['__parentId'])]},
          {"e": ["shopify/line_item_id", lid], "a": "line/sku", "v": ["sku/code", sku]}]
write(f, sd, 1, dry=DRY)
print('lines', len(lines))

# ---- duplicate accounts: same mailbox once normalised (plus-alias, dots, case) and same full name
def mailbox(e):
    a, b = e.lower().split('@')
    return a.split('+')[0].replace('.', '') + '@' + b
g = collections.defaultdict(list)
for c, (e, fn, ln) in cust.items():
    g[mailbox(e)].append(c)
f = []
skipped = 0
for k, cs in g.items():
    if len(cs) < 2:
        continue
    cs.sort(key=int)   # Shopify IDs grow with time: oldest first
    if len({(cust[c][1], cust[c][2]) for c in cs}) != 1:
        skipped += 1
        print('same mailbox, different names, not marked:', k, cs)
        continue
    for c in cs[1:]:
        f.append({"e": ["shopify/customer_id", c], "a": "core/same_as", "v": ["shopify/customer_id", cs[0]]})
print('same_as', len(f), 'skipped', skipped)
write(f, sd, 0.9, dry=DRY)

# ---- Amazon
ad = [doc('amazon/all_orders.txt')]
rows = list(csv.DictReader(open(f'{EX}/amazon/all_orders.txt'), delimiter='\t'))
f = []
for r in rows:
    oid, sku = r['amazon-order-id'], r['sku']
    k = f'{oid}/{sku}'
    f += [{"e": ["amazon/order_id", oid], "a": "amazon/order_id", "v": oid},
          {"e": ["amazon/order_line", k], "a": "amazon/order_line", "v": k},
          {"e": ["amazon/order_line", k], "a": "core/part_of", "v": ["amazon/order_id", oid]},
          {"e": ["amazon/order_line", k], "a": "line/sku", "v": ["amazon/seller_sku", sku]}]
write(f, ad, 1, dry=DRY)
print('amazon lines', len(rows))

fbad = [doc('amazon/fba_inbound_shipments.csv')]
fba = list(csv.DictReader(open(f'{EX}/amazon/fba_inbound_shipments.csv')))
fbaids = {r['Shipment ID'] for r in fba}
write([{"e": ["amazon/inbound_shipment_id", s], "a": "amazon/inbound_shipment_id", "v": s} for s in fbaids], fbad, 1, dry=DRY)

# ---- 3PL
names = {o['name'] for o in orders}
td = [doc('3pl/outbound.csv')]
ob = list(csv.DictReader(open(f'{EX}/3pl/outbound.csv')))
f = []
bad = collections.Counter()
for r in ob:
    ref, item = r['Order Reference'], r['Item Code']
    if ref in names:
        whole = ["shopify/order_name", ref]
    elif ref in fbaids:
        whole = ["amazon/inbound_shipment_id", ref]
    else:
        bad[ref] += 1
        continue
    k = f'{ref}/{item}'
    f += [{"e": ["tpl/outbound_key", k], "a": "tpl/outbound_key", "v": k},
          {"e": ["tpl/outbound_key", k], "a": "core/part_of", "v": whole},
          {"e": ["tpl/outbound_key", k], "a": "line/sku", "v": ["tpl/item_code", item]}]
print('outbound lines', len(ob), 'unresolved refs', dict(bad))
write(f, td, 1, dry=DRY)

rd = [doc('3pl/receipts.csv')]
rc = list(csv.DictReader(open(f'{EX}/3pl/receipts.csv')))
f = []
seen = set()
for r in rc:
    n = r['Receipt #']
    if n not in seen:
        seen.add(n)
        f.append({"e": ["tpl/receipt_no", n], "a": "tpl/receipt_no", "v": n})
        for po in [p.strip() for p in r['Reference'].split('/') if p.strip()]:
            assert re.fullmatch(r'PO-\d{4}-\d{4}', po), po
            f.append({"e": ["tpl/receipt_no", n], "a": "receipt/po", "v": ["po/number", po]})
    k = f"{n}/{r['Item Code']}"
    f += [{"e": ["tpl/receipt_line", k], "a": "tpl/receipt_line", "v": k},
          {"e": ["tpl/receipt_line", k], "a": "core/part_of", "v": ["tpl/receipt_no", n]},
          {"e": ["tpl/receipt_line", k], "a": "line/sku", "v": ["tpl/item_code", r['Item Code']]}]
print('receipts', len(seen), 'lines', len(rc), 'receipts without PO', sum(1 for n in seen if not any(x['Receipt #'] == n and x['Reference'] for x in rc)))
write(f, rd, 1, dry=DRY)
