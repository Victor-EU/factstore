"""What the simulation produces: the business's records, the messages around them, and the
ground truth a skill is scored against."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from .catalog import Sku, Supplier
from .people import Person


@dataclass(eq=False)
class PoLine:
    po: "Po"
    line_no: int
    sku: Sku
    quantity: int
    unit_price: Decimal = Decimal(0)
    shipped: int = 0

    @property
    def key(self) -> str:
        return f"{self.po.number}/{self.line_no}"

    @property
    def amount(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def cartons(self) -> int:
        return -(-self.quantity // self.sku.family.carton.units)


@dataclass(eq=False)
class QcInspection:
    report_no: str
    po: "Po"
    on: date
    inspector: str
    result: str                  # PASS or FAIL
    sample_size: int
    defects: list[tuple[str, str, int]]  # (description, severity, count)


@dataclass(eq=False)
class Po:
    number: str
    supplier: Supplier
    placed: datetime
    lines: list[PoLine] = field(default_factory=list)
    status: str = "draft"
    pi_number: str | None = None
    pi_date: date | None = None
    etd: date | None = None      # the supplier's current promise, then the actual departure
    ready: date | None = None
    deposit_paid: date | None = None
    balance_paid: date | None = None
    inspections: list[QcInspection] = field(default_factory=list)
    shipments: list["Shipment"] = field(default_factory=list)
    route: str | None = None

    @property
    def currency(self) -> str:
        return self.supplier.currency

    @property
    def total(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal(0))

    @property
    def cbm(self) -> Decimal:
        return sum((line.cartons * line.sku.family.carton.cbm for line in self.lines), Decimal(0))


@dataclass(eq=False)
class ShipmentLine:
    po_line: PoLine
    quantity: int
    cartons: int


@dataclass(eq=False)
class Shipment:
    booking_no: str
    hbl: str
    mode: str                    # 40HQ, 20GP or LCL
    container_no: str | None
    seal_no: str | None
    origin: str                  # UN/LOCODE
    destination: str
    vessel: str
    voyage: str
    etd: datetime
    eta: datetime
    freight: Decimal             # USD
    lines: list[ShipmentLine] = field(default_factory=list)
    status: str = "booked"
    delivered: datetime | None = None
    entry: "CustomsEntry | None" = None
    receipt: "Receipt | None" = None

    @property
    def pos(self) -> list[Po]:
        return list(dict.fromkeys(line.po_line.po for line in self.lines))

    @property
    def cbm(self) -> Decimal:
        return sum((line.cartons * line.po_line.sku.family.carton.cbm for line in self.lines), Decimal(0))

    @property
    def gross_kg(self) -> Decimal:
        return sum((line.cartons * line.po_line.sku.family.carton.gross_kg for line in self.lines), Decimal(0))


@dataclass(eq=False)
class EntryLine:
    po_line: PoLine
    quantity: int
    value_usd: Decimal
    general: Decimal
    section_301: Decimal
    additional: Decimal

    @property
    def duty(self) -> Decimal:
        return self.general + self.section_301 + self.additional


@dataclass(eq=False)
class CustomsEntry:
    entry_no: str
    shipment: Shipment
    filed: date
    lines: list[EntryLine]
    mpf: Decimal
    hmf: Decimal
    brokerage: Decimal

    @property
    def duty(self) -> Decimal:
        return sum((line.duty for line in self.lines), Decimal(0))

    @property
    def total(self) -> Decimal:
        return self.duty + self.mpf + self.hmf


@dataclass(eq=False)
class ReceiptLine:
    sku: Sku
    expected: int
    received: int
    damaged: int


@dataclass(eq=False)
class Receipt:
    receipt_no: str
    asn_no: str
    shipment: Shipment
    received_at: datetime
    lines: list[ReceiptLine]


@dataclass(eq=False)
class FbaShipment:
    shipment_id: str
    name: str
    created: datetime
    destination: str             # fulfilment centre code
    lines: list[list]            # [sku, shipped, received]
    shipped: datetime | None = None
    received: datetime | None = None

    def status(self, now: datetime) -> str:
        if self.received and self.received <= now:
            return "CLOSED"
        if self.shipped and self.shipped <= now:
            return "IN_TRANSIT"
        return "WORKING"


@dataclass(eq=False, slots=True)
class Customer:
    id: int
    person: Person
    created: datetime
    duplicate_of: int | None = None  # ground truth: the same person under another account


@dataclass(eq=False)
class ShopifyLine:
    id: int
    sku: Sku
    quantity: int
    price: Decimal
    discount: Decimal


@dataclass(eq=False)
class ShopifyOrder:
    id: int
    number: int
    created: datetime            # UTC
    customer: Customer
    address: Person
    lines: list[ShopifyLine]
    discount_code: str | None
    shipping: Decimal
    shipping_method: str
    tax: Decimal
    source: str
    fulfilled: datetime | None
    cancelled: datetime | None = None
    cancel_reason: str | None = None
    refunds: list[tuple[datetime, Decimal]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"#{self.number}"

    @property
    def subtotal(self) -> Decimal:
        return sum((line.price * line.quantity - line.discount for line in self.lines), Decimal(0))

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.shipping + self.tax


@dataclass(eq=False)
class AmazonLine:
    sku: Sku
    quantity: int
    item_price: Decimal          # line total, as Amazon reports it
    item_tax: Decimal
    promotion_discount: Decimal
    promotion_id: str | None


@dataclass(eq=False)
class AmazonOrder:
    id: str
    purchased: datetime          # UTC
    lines: list[AmazonLine]
    city: str
    state: str
    zip: str
    service_level: str
    shipped: datetime | None
    cancelled: bool = False


@dataclass(eq=False)
class Bill:
    id: int
    vendor: str
    on: date
    due: date
    doc_number: str
    memo: str
    lines: list[tuple[str, Decimal]]   # (account, amount)
    currency: str
    exchange_rate: Decimal             # home currency (USD) per unit
    paid: date | None = None
    payment_id: int | None = None

    @property
    def amount(self) -> Decimal:
        return sum((amount for _, amount in self.lines), Decimal(0))


@dataclass(eq=False)
class Message:
    at: datetime
    chat: str                    # supplier code
    sender: str
    text: str


@dataclass(eq=False)
class Email:
    at: datetime
    sender: tuple[str, str]
    to: tuple[str, str]
    subject: str
    body: str
    message_id: str
    in_reply_to: str | None = None
    attachments: tuple[str, ...] = ()


@dataclass(eq=False)
class Document:
    kind: str                    # proforma_invoice, commercial_invoice, qc_report
    filename: str
    issued: date
    subject: object              # Po, (Shipment, Po) or QcInspection


@dataclass(eq=False)
class Statement:
    """Ground truth: something a message or document asserts, for scoring an ingestion skill."""

    source: str                  # wechat, email or pdf
    ref: str                     # file name or message ID
    at: datetime
    subject: str                 # PO number, booking number or entry number
    field: str
    value: str


@dataclass(eq=False)
class Event:
    """A change to the records the store is primary for, in time order: what the loader writes."""

    at: datetime
    kind: str
    subject: object
    data: dict = field(default_factory=dict)


@dataclass(eq=False)
class InventoryPosition:
    sku: Sku
    location: str
    quantity: int
    counted_at: datetime

    @property
    def key(self) -> str:
        return f"{self.sku.code}@{self.location}"
