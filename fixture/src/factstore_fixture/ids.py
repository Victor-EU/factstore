"""Identifiers in the formats the real systems issue, with check digits where they have them."""

import random

ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
UPPER_ALNUM_NO_IO = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"


def iso6346(owner: str, serial: int) -> str:
    """A container number: three-letter owner code, category U, six-digit serial, ISO 6346 check digit."""
    code = f"{owner}U{serial:06d}"
    values, v = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        values[ch] = v
        v += 1
    total = sum((values[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(code))
    return code + str(total % 11 % 10)


def upc_a(company_prefix: str, item: int) -> str:
    """A 12-digit UPC-A (GTIN-12) with its check digit."""
    body = f"{company_prefix}{item:0{11 - len(company_prefix)}d}"
    odd = sum(int(d) for d in body[0::2])
    even = sum(int(d) for d in body[1::2])
    return body + str((10 - (3 * odd + even) % 10) % 10)


def luhn(digits: str) -> str:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return str((10 - total % 10) % 10)


def cbp_entry(filer: str, serial: int) -> str:
    """A US customs entry number: filer code, seven digits, check digit (Luhn here)."""
    body = f"{serial:07d}"
    return f"{filer}-{body}-{luhn(body)}"


def amazon_order_id(rng: random.Random) -> str:
    return f"11{rng.choice('1234')}-{rng.randrange(10**7):07d}-{rng.randrange(10**7):07d}"


def asin(rng: random.Random) -> str:
    return "B0" + "".join(rng.choice(ALNUM) for _ in range(8))


def fnsku(rng: random.Random) -> str:
    return "X00" + "".join(rng.choice(ALNUM) for _ in range(7))


def fba_shipment_id(rng: random.Random) -> str:
    return "FBA19" + "".join(rng.choice(UPPER_ALNUM_NO_IO) for _ in range(7))


def shopify_gid(kind: str, id_: int) -> str:
    return f"gid://shopify/{kind}/{id_}"
