"""Synthetic shoppers. Names are common US names; every email address is at a reserved
example domain and every phone number is in the 555-01xx fictional range, so none of it
can reach a real person."""

import random
from dataclasses import dataclass
from decimal import Decimal

from .clock import US_CENTRAL, US_EAST, US_MOUNTAIN, US_WEST

FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Elijah", "Sophia", "James", "Mia", "Lucas", "Amelia", "Mateo",
         "Harper", "Ethan", "Evelyn", "Aiden", "Chloe", "Daniel", "Priya", "Wei", "Fatima", "Diego", "Hannah", "Omar",
         "Grace", "Jin", "Nora", "Samuel", "Leah", "Kofi", "Rachel", "Megan", "Jessica", "Sarah", "Lauren", "Ashley",
         "Emily", "Nicole", "Katie", "Anna", "Julia", "Maria", "Sofia", "Isabel", "Hana", "Yuki", "Aisha", "Zoe",
         "Claire", "Molly", "Caroline", "Erin", "Kelly", "Brian", "Michael", "David", "Chris", "Matt", "Kevin", "Ryan"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
        "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson",
        "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Patel", "Kim", "Chen", "Okafor",
        "Cohen", "Murphy", "Singh", "Ali", "Brooks", "Sullivan"]
STREETS = ["Maple St", "Oak Ave", "Cedar Ln", "Park Pl", "Elm St", "Washington Ave", "Lake Dr", "Hillside Rd",
           "Sunset Blvd", "Willow Way", "Highland Ave", "Main St", "Pine St", "River Rd", "Church St", "Spring St",
           "Chestnut St", "Prospect Ave", "Meadow Ln", "Franklin St"]
EMAIL_DOMAINS = [("example.com", 40), ("example.net", 25), ("example.org", 20), ("mail.example", 15)]

# city, state, ZIP, time zone, combined sales tax rate, population weight
CITIES = [
    ("Los Angeles", "CA", "90026", US_WEST, "0.0950", 9), ("San Francisco", "CA", "94110", US_WEST, "0.08625", 5),
    ("San Diego", "CA", "92104", US_WEST, "0.0775", 4), ("Oakland", "CA", "94610", US_WEST, "0.1025", 3),
    ("Seattle", "WA", "98103", US_WEST, "0.1035", 4), ("Portland", "OR", "97214", US_WEST, "0", 3),
    ("Phoenix", "AZ", "85004", US_MOUNTAIN, "0.086", 3), ("Denver", "CO", "80205", US_MOUNTAIN, "0.0881", 3),
    ("Austin", "TX", "78704", US_CENTRAL, "0.0825", 4), ("Houston", "TX", "77006", US_CENTRAL, "0.0825", 4),
    ("Dallas", "TX", "75206", US_CENTRAL, "0.0825", 3), ("Chicago", "IL", "60614", US_CENTRAL, "0.1025", 5),
    ("Minneapolis", "MN", "55408", US_CENTRAL, "0.08025", 2), ("Nashville", "TN", "37206", US_CENTRAL, "0.0925", 2),
    ("Atlanta", "GA", "30306", US_EAST, "0.089", 3), ("Miami", "FL", "33137", US_EAST, "0.07", 3),
    ("Orlando", "FL", "32803", US_EAST, "0.065", 2), ("Raleigh", "NC", "27604", US_EAST, "0.0725", 2),
    ("Washington", "DC", "20009", US_EAST, "0.06", 2), ("Philadelphia", "PA", "19125", US_EAST, "0.08", 3),
    ("Brooklyn", "NY", "11215", US_EAST, "0.08875", 6), ("New York", "NY", "10025", US_EAST, "0.08875", 5),
    ("Hoboken", "NJ", "07030", US_EAST, "0.06625", 2), ("Boston", "MA", "02130", US_EAST, "0.0625", 3),
    ("Columbus", "OH", "43206", US_EAST, "0.075", 2), ("Detroit", "MI", "48207", US_EAST, "0.06", 2),
]
CITY_WEIGHTS = [c[5] for c in CITIES]


@dataclass(frozen=True, slots=True)
class Person:
    first: str
    last: str
    email: str
    phone: str | None
    address1: str
    city: str
    state: str
    zip: str
    tz: object
    tax_rate: Decimal


def person(rng: random.Random, n: int) -> Person:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    city, state, zip_, tz, tax, _ = rng.choices(CITIES, weights=CITY_WEIGHTS)[0]
    return Person(first, last, email(rng, first, last, n), phone(rng) if rng.random() < 0.35 else None,
                  f"{rng.randint(2, 2999)} {rng.choice(STREETS)}", city, state, zip_, tz, Decimal(tax))


def email(rng: random.Random, first: str, last: str, n: int) -> str:
    domain = rng.choices([d for d, _ in EMAIL_DOMAINS], weights=[w for _, w in EMAIL_DOMAINS])[0]
    local = rng.choice([f"{first}.{last}", f"{first}{last}", f"{first[0]}{last}", f"{first}{last}{n % 97}",
                        f"{first}_{last[0]}{n % 1000}", f"{last}.{first}"]).lower()
    return f"{local}@{domain}"


def alias_email(rng: random.Random, original: str) -> str:
    """The same person signing up again: a plus alias or a different provider."""
    local, domain = original.split("@")
    if rng.random() < 0.5:
        return f"{local}+{rng.choice(['shop', 'orders', 'home', '2'])}@{domain}"
    other = [d for d, _ in EMAIL_DOMAINS if d != domain]
    return f"{local}@{rng.choice(other)}"


def phone(rng: random.Random) -> str:
    return f"+1{rng.choice(['212', '312', '415', '512', '617', '718', '206', '303', '404', '503'])}55501{rng.randint(0, 99):02d}"
