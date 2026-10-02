"""The two calendars that drive the business, and the clock.

China's factory calendar (public holidays, the Chinese New Year shutdown, Golden Week)
decides when goods get made. The US retail calendar (seasons, gifting days, Prime Day,
sales) decides when they sell. Chinese holidays follow the published 2026 schedule.
Prime Day 2026's dates and the FX path are assumptions.
"""

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")
US_EAST = ZoneInfo("America/New_York")
US_CENTRAL = ZoneInfo("America/Chicago")
US_MOUNTAIN = ZoneInfo("America/Denver")
US_WEST = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")

SIM_START = date(2025, 10, 1)  # warm-up, so the year opens with stock on hand and POs in flight
YEAR_START = date(2026, 1, 1)  # exports and the loader cover the year to date
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=US_EAST)
TODAY = NOW.date()

FACTORY_CLOSED = [
    (date(2025, 10, 1), date(2025, 10, 7)),   # National Day 2025
    (date(2026, 1, 1), date(2026, 1, 3)),     # New Year
    (date(2026, 2, 9), date(2026, 3, 1)),     # Chinese New Year, Feb 17: official Feb 15-23, workers travel either side
    (date(2026, 4, 4), date(2026, 4, 6)),     # Qingming
    (date(2026, 5, 1), date(2026, 5, 5)),     # Labour Day
    (date(2026, 6, 19), date(2026, 6, 21)),   # Dragon Boat
    (date(2026, 9, 25), date(2026, 9, 27)),   # Mid-Autumn
    (date(2026, 10, 1), date(2026, 10, 7)),   # National Day: Golden Week
]
SLOW_RESTART = (date(2026, 3, 2), date(2026, 3, 15), 0.6)  # capacity while workers trickle back after CNY
CNY_DAY = date(2026, 2, 17)


def factory_capacity(d: date) -> float:
    """Share of a normal day's output. Factories work Monday to Saturday."""
    if d.weekday() == 6 or any(a <= d <= b for a, b in FACTORY_CLOSED):
        return 0.0
    a, b, share = SLOW_RESTART
    return share if a <= d <= b else 1.0


def add_factory_days(start: date, days: float) -> date:
    """The date `days` full working days of output after `start`."""
    d, done = start, 0.0
    while done < days:
        d += timedelta(days=1)
        done += factory_capacity(d)
    return d


def is_us_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in US_HOLIDAYS


def add_us_business_days(start: date, n: int) -> date:
    d = start
    while n > 0:
        d += timedelta(days=1)
        if is_us_business_day(d):
            n -= 1
    return d


US_HOLIDAYS = {date(2025, 11, 27), date(2025, 12, 25), date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
               date(2026, 5, 25), date(2026, 7, 3), date(2026, 9, 7)}

# --- demand -------------------------------------------------------------------------------

MONTH_FACTOR = {1: 0.82, 2: 0.80, 3: 0.90, 4: 0.95, 5: 1.05, 6: 0.95, 7: 1.0, 8: 0.95, 9: 1.0, 10: 1.1,
                11: 1.65, 12: 1.95}
WEEKDAY_FACTOR = {"shopify": (1.12, 1.0, 0.97, 0.95, 0.88, 0.93, 1.15),
                  "amazon": (1.05, 1.0, 1.0, 0.98, 0.95, 1.0, 1.02)}
# (first day, last day, Shopify factor, Amazon factor, Shopify discount code, percent off)
RETAIL_EVENTS = [
    (date(2025, 10, 7), date(2025, 10, 8), 1.0, 2.1, None, 0),          # Prime Big Deal Days
    (date(2025, 11, 27), date(2025, 12, 1), 3.1, 2.4, "BFCM25", 25),    # Black Friday / Cyber Monday
    (date(2025, 12, 2), date(2025, 12, 17), 1.3, 1.25, None, 0),        # gift shopping
    (date(2025, 12, 22), date(2025, 12, 31), 0.6, 0.75, None, 0),       # too late to ship for Christmas
    (date(2026, 2, 6), date(2026, 2, 13), 1.15, 1.1, None, 0),          # Valentine's Day
    (date(2026, 5, 1), date(2026, 5, 8), 1.6, 1.35, "MOM15", 15),       # Mother's Day, May 10
    (date(2026, 5, 22), date(2026, 5, 25), 1.45, 1.1, "MEMORIAL15", 15),
    (date(2026, 6, 13), date(2026, 6, 19), 1.1, 1.1, None, 0),          # Father's Day
    (date(2026, 7, 1), date(2026, 7, 6), 1.4, 0.9, "JULY4", 15),        # July 4 sale; Amazon shoppers wait for Prime Day
    (date(2026, 7, 7), date(2026, 7, 10), 0.92, 3.2, None, 0),          # Prime Day (dates assumed)
    (date(2026, 8, 10), date(2026, 8, 31), 1.05, 1.05, None, 0),        # back to school
    (date(2026, 9, 4), date(2026, 9, 7), 1.5, 1.15, "LABORDAY20", 20),
]
BASE_ORDERS_PER_DAY = {"shopify": 92.0, "amazon": 128.0}  # October 2025, before seasonality
MONTHLY_GROWTH = 0.025

# Local hour of day weights for when people order.
HOUR_WEIGHTS = (0.5, 0.3, 0.2, 0.15, 0.15, 0.25, 0.5, 0.9, 1.2, 1.4, 1.5, 1.6, 1.8, 1.8, 1.6, 1.5, 1.5, 1.6, 1.8,
                2.1, 2.3, 2.2, 1.7, 1.0)


def demand_factor(d: date, channel: str) -> float:
    months = (d.year - SIM_START.year) * 12 + d.month - SIM_START.month
    factor = MONTH_FACTOR[d.month] * WEEKDAY_FACTOR[channel][d.weekday()] * (1 + MONTHLY_GROWTH) ** months
    for first, last, shopify, amazon, *_ in RETAIL_EVENTS:
        if first <= d <= last:
            factor *= shopify if channel == "shopify" else amazon
    return factor


def season_factor(d: date) -> float:
    """What a planner expects for a day, both channels together: the forecast's shape."""
    return (demand_factor(d, "shopify") * BASE_ORDERS_PER_DAY["shopify"]
            + demand_factor(d, "amazon") * BASE_ORDERS_PER_DAY["amazon"]) / sum(BASE_ORDERS_PER_DAY.values())


def promotion(d: date) -> tuple[str | None, int]:
    for first, last, _, _, code, percent in RETAIL_EVENTS:
        if first <= d <= last and code:
            return code, percent
    return None, 0


# --- money and freight --------------------------------------------------------------------


def cny_per_usd(d: date) -> Decimal:
    """An assumed, gently drifting exchange rate."""
    days = (d - SIM_START).days
    return Decimal(str(round(7.13 - 0.00025 * days + 0.012 * math.sin(days / 11), 4)))


PORTS = {"CNNGB": "Ningbo", "CNYTN": "Yantian", "CNNSA": "Nansha", "CNXMN": "Xiamen",
         "USNYC": "New York/Newark", "USLAX": "Los Angeles"}
# Weekly sailings: weekday of departure, and port-to-port days.
SAILINGS = {
    ("CNNGB", "USNYC"): (4, 33), ("CNNGB", "USLAX"): (6, 16),
    ("CNYTN", "USNYC"): (2, 31), ("CNYTN", "USLAX"): (0, 15),
    ("CNNSA", "USNYC"): (3, 32), ("CNNSA", "USLAX"): (1, 16),
    ("CNXMN", "USNYC"): (1, 31), ("CNXMN", "USLAX"): (5, 15),
}
VESSELS = ["MV Pacific Lantern", "MV Coral Meridian", "MV Jade Horizon", "MV Northern Ardent", "MV Silver Estuary",
           "MV Harbor Crest", "MV Eastern Paragon", "MV Golden Tide", "MV Azure Pinnacle", "MV Celestial Bay"]


def next_sailing(port: str, route: str, not_before: date) -> date:
    weekday, _ = SAILINGS[(port, route)]
    return not_before + timedelta(days=(weekday - not_before.weekday()) % 7)


def at(d: date, hour: int, tz, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), tz)
