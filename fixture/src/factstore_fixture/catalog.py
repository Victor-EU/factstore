"""Who makes what: Acme Hearth's suppliers, product families and SKUs.

All companies and people are fictional. Personal and company contact details use the
reserved .example domain and 555-01xx numbers, so none can reach anyone real.
"""

import random
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from . import ids

BRAND = "Acme Hearth"
BRAND_LEGAL = "Acme Hearth Inc."
BRAND_ADDRESS = "141 Flushing Ave, Unit 512, Brooklyn, NY 11205, USA"
BRAND_DOMAIN = "acmehearth.example"
BRAND_OPS = ("Maya Ortiz", "maya@acmehearth.example")
UPC_PREFIX = "860005821"

FORWARDER = ("Pacific Bridge Logistics", "pacificbridge.example")
BROKER = ("Harborline Customs Brokerage", "harborline.example", "HB7")  # name, domain, CBP filer code
TPL = ("Garden State Fulfillment", "gsfulfillment.example", "Edison, NJ")


@dataclass(frozen=True)
class PriceChange:
    effective: date
    announced: date
    percent: Decimal
    reason_en: str
    reason_cn: str


@dataclass(frozen=True, eq=False)
class Supplier:
    code: str
    name: str
    name_cn: str
    qb_name: str               # how QuickBooks lists the vendor
    address: str
    port: str                  # port of loading
    port_locode: str
    currency: str
    payment_terms: str
    deposit: Decimal           # share of the PO paid up front
    sales: str                 # main contact, as they sign
    sales_wechat: str          # their WeChat display name
    item_prefix: str           # how the factory writes its own item codes; "" means bare numbers
    moq: int                   # minimum units per SKU per order
    price_changes: tuple[PriceChange, ...] = ()

    @property
    def incoterm(self) -> str:
        return f"FOB {self.port}"


SUPPLIERS = [
    Supplier("NBBW", "Ningbo Mingtu Housewares Co., Ltd.", "宁波明途家居用品有限公司", "Mingtu Housewares",
             "No. 88 Xingye Road, Yinzhou District, Ningbo, Zhejiang", "Ningbo", "CNNGB", "USD",
             "T/T 30% deposit, 70% before shipment", Decimal("0.30"), "Lily Chen", "Lily陈丽-明途家居", "MT-", 300),
    Supplier("SZHT", "Shenzhen Hetai Electric Appliance Co., Ltd.", "深圳市和泰电器有限公司", "Hetai Electric (SZ)",
             "Building 3, Fuhai Industrial Park, Bao'an District, Shenzhen, Guangdong", "Yantian", "CNYTN", "USD",
             "T/T 30% deposit, 70% against B/L copy", Decimal("0.30"), "Kevin Zhou", "Kevin周-和泰电器", "HT", 500,
             (PriceChange(date(2026, 7, 1), date(2026, 6, 12), Decimal("-2"), "volume rebate on the 2026 orders",
                          "今年订单量大，给您降价2%"),)),
    Supplier("YWLX", "Yiwu Lanxin Textile Co., Ltd.", "义乌市蓝欣纺织品有限公司", "Lanxin Textile",
             "No. 1216 Chouzhou North Road, Yiwu, Zhejiang", "Ningbo", "CNNGB", "CNY",
             "T/T 50% deposit, 50% before shipment", Decimal("0.50"), "Amy Wang", "Amy王-蓝欣纺织", "", 500,
             (PriceChange(date(2026, 8, 15), date(2026, 7, 28), Decimal("5"), "cotton yarn prices are up",
                          "棉纱涨价了，8月15号以后的订单单价上调5%"),)),
    Supplier("DGRF", "Dongguan Ruifeng Silicone Products Co., Ltd.", "东莞市瑞丰硅胶制品有限公司", "Ruifeng Silicone",
             "No. 6 Hengli Avenue, Hengli Town, Dongguan, Guangdong", "Yantian", "CNYTN", "USD",
             "T/T 30% deposit, 70% before shipment", Decimal("0.30"), "Jason Li", "Jason李-瑞丰硅胶", "RF", 500),
    Supplier("FSMJ", "Foshan Mingjia Ceramics Co., Ltd.", "佛山市明嘉陶瓷有限公司", "Mingjia Ceramics",
             "No. 32 Jihua 5th Road, Chancheng District, Foshan, Guangdong", "Nansha", "CNNSA", "CNY",
             "T/T 40% deposit, 60% before shipment", Decimal("0.40"), "Grace Huang", "Grace黄-明嘉陶瓷", "", 500,
             (PriceChange(date(2026, 3, 1), date(2026, 1, 20), Decimal("3"), "labour costs after Chinese New Year",
                          "春节后工人工资上涨，3月1号起单价上调3%"),)),
    Supplier("XMYD", "Xiamen Yuanda Bamboo Products Co., Ltd.", "厦门远达竹木制品有限公司", "Yuanda Bamboo",
             "No. 199 Tongji Road, Tong'an District, Xiamen, Fujian", "Xiamen", "CNXMN", "USD",
             "T/T 30% deposit, 70% against B/L copy", Decimal("0.30"), "Eric Lin", "Eric林-远达竹木", "YD-", 300),
    Supplier("NBQS", "Ningbo Qisheng Stainless Steel Co., Ltd.", "宁波启盛不锈钢制品有限公司", "Qisheng Stainless",
             "No. 515 Huangjia Road, Cixi, Ningbo, Zhejiang", "Ningbo", "CNNGB", "USD",
             "T/T 30% deposit, 70% before shipment", Decimal("0.30"), "Sunny Xu", "Sunny徐-启盛", "QS", 500,
             (PriceChange(date(2026, 5, 1), date(2026, 4, 10), Decimal("4"), "stainless steel coil prices",
                          "不锈钢原材料涨价，5月1号开始单价上调4%"),)),
    Supplier("HZTY", "Hangzhou Tianyi Glassware Co., Ltd.", "杭州天艺玻璃制品有限公司", "Tianyi Glassware",
             "No. 77 Qiaonan Road, Xiaoshan District, Hangzhou, Zhejiang", "Ningbo", "CNNGB", "USD",
             "T/T 100% before shipment", Decimal("0"), "Coco Zhang", "Coco张-天艺玻璃", "", 300),
]


@dataclass(frozen=True)
class Carton:
    units: int
    length_cm: int
    width_cm: int
    height_cm: int
    gross_kg: Decimal

    @property
    def cbm(self) -> Decimal:
        return (Decimal(self.length_cm * self.width_cm * self.height_cm) / 1_000_000).quantize(Decimal("0.0001"))


@dataclass(frozen=True, eq=False)
class Family:
    supplier: str
    code: str
    title: str
    title_cn: str
    product_type: str
    hs_code: str
    duty_general: Decimal       # HTSUS column 1 rate, illustrative
    duty_301: Decimal           # Section 301 rate, illustrative
    retail: Decimal             # USD
    cost_usd: Decimal
    carton: Carton
    production_days: int        # factory working days after the deposit lands
    damage_rate: float          # share of units the 3PL books in as damaged
    variants: tuple[str, ...]
    launches: dict = field(default_factory=dict)  # variant -> launch date, for SKUs new this year


ADDITIONAL_CHINA_DUTY = Decimal("0.10")  # illustrative; actual rates have changed often
MPF_RATE, MPF_MIN, MPF_MAX = Decimal("0.003464"), Decimal("33.58"), Decimal("651.50")
HMF_RATE = Decimal("0.00125")

FAMILIES = [
    Family("NBBW", "KTL", "Enamel Stovetop Kettle 2.5L", "搪瓷烧水壶 2.5升", "Kettles", "7323.94.0010", Decimal("0.027"),
           Decimal("0.25"), Decimal("64.00"), Decimal("11.20"), Carton(6, 52, 38, 30, Decimal("9.5")), 35, 0.004,
           ("Black", "Cream", "Sage")),
    Family("NBBW", "SAU", "Enamel Saucepan 18cm", "搪瓷奶锅 18cm", "Cookware", "7323.94.0010", Decimal("0.027"),
           Decimal("0.25"), Decimal("48.00"), Decimal("8.40"), Carton(8, 45, 40, 28, Decimal("8.8")), 35, 0.004,
           ("Black", "Cream")),
    Family("NBBW", "CSR", "Enamel Casserole 24cm", "搪瓷炖锅 24cm", "Cookware", "7323.94.0010", Decimal("0.027"),
           Decimal("0.25"), Decimal("89.00"), Decimal("16.50"), Carton(4, 56, 30, 32, Decimal("12.0")), 38, 0.004,
           ("Black", "Cream", "Red", "Sage"), {"Sage": date(2026, 5, 1)}),
    Family("SZHT", "EKT", "Electric Gooseneck Kettle 1L", "电热鹅颈壶 1升", "Small Appliances", "8516.79.0000",
           Decimal("0.027"), Decimal("0.25"), Decimal("79.00"), Decimal("18.90"), Carton(6, 48, 34, 30, Decimal("7.2")),
           30, 0.002, ("Black", "White")),
    Family("SZHT", "HMX", "Hand Mixer 5-Speed", "手持打蛋器 五档", "Small Appliances", "8509.40.0000",
           Decimal("0.042"), Decimal("0.25"), Decimal("59.00"), Decimal("13.10"), Carton(8, 50, 42, 36, Decimal("9.8")),
           30, 0.002, ("White", "Grey")),
    Family("SZHT", "MLK", "Milk Frother", "电动奶泡器", "Small Appliances", "8509.80.5095", Decimal("0.042"),
           Decimal("0.25"), Decimal("29.00"), Decimal("5.60"), Carton(48, 52, 38, 30, Decimal("8.4")), 25, 0.001,
           ("Black", "Silver")),
    Family("YWLX", "TWL", "Waffle Tea Towels, Set of 3", "华夫格茶巾 3条装", "Kitchen Textiles", "6302.60.0020",
           Decimal("0.091"), Decimal("0.075"), Decimal("24.00"), Decimal("3.10"), Carton(40, 60, 40, 35, Decimal("12.5")),
           25, 0.0, ("Natural", "Charcoal", "Rust")),
    Family("YWLX", "APR", "Linen Apron", "亚麻围裙", "Kitchen Textiles", "6307.90.9891", Decimal("0.07"),
           Decimal("0.075"), Decimal("38.00"), Decimal("5.20"), Carton(50, 55, 40, 35, Decimal("11.0")), 22, 0.0,
           ("Natural", "Navy")),
    Family("YWLX", "MIT", "Quilted Oven Mitt", "夹棉隔热手套", "Kitchen Textiles", "6307.90.9891", Decimal("0.07"),
           Decimal("0.075"), Decimal("18.00"), Decimal("2.30"), Carton(60, 58, 42, 40, Decimal("9.0")), 22, 0.0,
           ("Natural", "Charcoal")),
    Family("DGRF", "SPT", "Silicone Spatula Set", "硅胶铲套装", "Baking", "3924.10.4000", Decimal("0.034"),
           Decimal("0.25"), Decimal("22.00"), Decimal("2.90"), Carton(48, 50, 35, 30, Decimal("10.2")), 20, 0.0,
           ("Grey", "Sage")),
    Family("DGRF", "BMT", "Silicone Baking Mat", "硅胶烘焙垫", "Baking", "3924.10.4000", Decimal("0.034"),
           Decimal("0.25"), Decimal("19.00"), Decimal("2.40"), Carton(60, 45, 35, 25, Decimal("13.0")), 20, 0.0,
           ("Half Sheet", "Quarter Sheet")),
    Family("DGRF", "LID", "Silicone Stretch Lids, Set of 6", "硅胶保鲜盖 6件套", "Food Storage", "3924.10.4000",
           Decimal("0.034"), Decimal("0.25"), Decimal("16.00"), Decimal("1.70"), Carton(72, 48, 36, 28, Decimal("9.6")),
           18, 0.0, ("Clear",), {"Clear": date(2026, 6, 1)}),
    Family("FSMJ", "MUG", "Stoneware Mug 12oz", "粗陶马克杯 12oz", "Drinkware", "6912.00.4810", Decimal("0.098"),
           Decimal("0.075"), Decimal("18.00"), Decimal("2.10"), Carton(36, 55, 38, 40, Decimal("15.5")), 35, 0.012,
           ("Speckled White", "Slate", "Clay")),
    Family("FSMJ", "PLT", "Stoneware Dinner Plate", "粗陶餐盘", "Dinnerware", "6912.00.4810", Decimal("0.098"),
           Decimal("0.075"), Decimal("22.00"), Decimal("2.80"), Carton(24, 32, 32, 40, Decimal("18.0")), 35, 0.012,
           ("Speckled White", "Slate")),
    Family("FSMJ", "BWL", "Stoneware Bowl", "粗陶碗", "Dinnerware", "6912.00.4810", Decimal("0.098"), Decimal("0.075"),
           Decimal("20.00"), Decimal("2.50"), Carton(24, 40, 40, 36, Decimal("15.0")), 35, 0.012,
           ("Speckled White", "Slate", "Clay")),
    Family("XMYD", "CTB", "Bamboo Cutting Board", "竹砧板", "Serveware", "4419.11.0000", Decimal("0.032"),
           Decimal("0.25"), Decimal("34.00"), Decimal("4.80"), Carton(20, 48, 32, 35, Decimal("16.0")), 30, 0.0,
           ("Small", "Large")),
    Family("XMYD", "UTN", "Bamboo Utensil Set", "竹餐具套装", "Serveware", "4419.12.0000", Decimal("0.032"),
           Decimal("0.25"), Decimal("26.00"), Decimal("3.30"), Carton(40, 40, 30, 30, Decimal("8.5")), 28, 0.0,
           ("Natural",)),
    Family("XMYD", "TRY", "Bamboo Serving Tray", "竹托盘", "Serveware", "4419.19.9000", Decimal("0.032"),
           Decimal("0.25"), Decimal("42.00"), Decimal("6.10"), Carton(12, 50, 35, 30, Decimal("11.0")), 30, 0.0,
           ("Natural",)),
    Family("NBQS", "TMB", "Insulated Tumbler 20oz", "保温杯 20oz", "Drinkware", "9617.00.1000", Decimal("0.072"),
           Decimal("0.075"), Decimal("32.00"), Decimal("4.60"), Carton(24, 55, 37, 30, Decimal("9.6")), 28, 0.001,
           ("Black", "Sage", "Sand"), {"Sand": date(2026, 3, 15)}),
    Family("NBQS", "BTL", "Insulated Bottle 750ml", "保温瓶 750ml", "Drinkware", "9617.00.1000", Decimal("0.072"),
           Decimal("0.075"), Decimal("36.00"), Decimal("5.10"), Carton(24, 50, 34, 30, Decimal("9.0")), 28, 0.001,
           ("Black", "Sage")),
    Family("NBQS", "LBX", "Stainless Lunch Box", "不锈钢饭盒", "Food Storage", "7323.93.0080", Decimal("0.02"),
           Decimal("0.25"), Decimal("34.00"), Decimal("5.90"), Carton(20, 52, 40, 30, Decimal("10.5")), 25, 0.001,
           ("Silver",)),
    Family("HZTY", "JAR", "Glass Storage Jar 1L", "玻璃储物罐 1升", "Food Storage", "7013.49.9000", Decimal("0.072"),
           Decimal("0.25"), Decimal("21.00"), Decimal("2.60"), Carton(12, 45, 35, 30, Decimal("12.5")), 30, 0.015,
           ("Bamboo Lid", "Steel Lid")),
    Family("HZTY", "TPT", "Glass Teapot 1L", "玻璃茶壶 1升", "Tea", "7013.49.9000", Decimal("0.072"), Decimal("0.25"),
           Decimal("39.00"), Decimal("5.40"), Carton(12, 48, 36, 34, Decimal("9.5")), 30, 0.015, ("Clear",)),
    Family("HZTY", "CNR", "Glass Canister Set", "玻璃密封罐套装", "Food Storage", "7013.49.9000", Decimal("0.072"),
           Decimal("0.25"), Decimal("48.00"), Decimal("7.20"), Carton(6, 50, 35, 30, Decimal("13.0")), 30, 0.015,
           ("Clear",)),
]

VARIANT_CODES = {
    "Black": "BLK", "Cream": "CRM", "Sage": "SGE", "Red": "RED", "White": "WHT", "Grey": "GRY", "Silver": "SLV",
    "Natural": "NAT", "Charcoal": "CHR", "Rust": "RST", "Navy": "NVY", "Clear": "CLR", "Speckled White": "SPW",
    "Slate": "SLT", "Clay": "CLY", "Small": "SML", "Large": "LRG", "Sand": "SND", "Bamboo Lid": "BAM",
    "Steel Lid": "STL", "Half Sheet": "HLF", "Quarter Sheet": "QTR",
}
VARIANT_CN = {
    "Black": "黑色", "Cream": "米白", "Sage": "鼠尾草绿", "Red": "红色", "White": "白色", "Grey": "灰色", "Silver": "银色",
    "Natural": "本色", "Charcoal": "炭灰", "Rust": "铁锈红", "Navy": "藏青", "Clear": "透明", "Speckled White": "白色带点",
    "Slate": "石板灰", "Clay": "陶土色", "Small": "小号", "Large": "大号", "Sand": "沙色", "Bamboo Lid": "竹盖",
    "Steel Lid": "钢盖", "Half Sheet": "半盘", "Quarter Sheet": "四分之一盘",
}
DISCONTINUED = {"AH-SAU-0002-CRM": date(2026, 6, 1)}  # no new POs after this date; sells through


@dataclass(frozen=True, eq=False)
class Sku:
    code: str
    family: Family
    variant: str
    supplier: Supplier
    upc: str
    factory_code: str             # the factory's own code; unique only within that factory
    tpl_item_code: str            # the 3PL's code
    tpl_client_sku: str           # what the 3PL's files show as our SKU: usually right, sometimes blank or mistyped
    shopify_product_id: int
    shopify_variant_id: int
    shopify_variant_sku: str      # the SKU field in the Shopify admin: usually ours, sometimes reformatted
    amazon_seller_sku: str | None
    asin: str | None
    fnsku: str | None
    popularity: float             # relative daily demand
    launched: date | None         # None: on sale before this year

    @property
    def title(self) -> str:
        return f"{self.family.title}, {self.variant}"

    @property
    def factory_item_key(self) -> str:
        """Factory codes are unique only per factory, so the identity value carries the supplier code
        (the default for design open question 4)."""
        return f"{self.supplier.code}:{self.factory_code}"

    @property
    def factory_description(self) -> str:
        """How the factory describes the item on its documents: their words, not ours."""
        return f"{self.family.title_cn} {VARIANT_CN[self.variant]} / {self.family.title.lower()} {self.variant.lower()}"


def build(seed: int) -> list[Sku]:
    rng = random.Random(f"{seed}:catalog")
    suppliers = {s.code: s for s in SUPPLIERS}
    skus, next_code = [], {}
    product_id = 9_041_000_000_000
    for f_no, family in enumerate(FAMILIES, 1):
        supplier = suppliers[family.supplier]
        on_amazon = rng.random() < 0.65
        product_id += rng.randint(30_000, 900_000)
        for variant in family.variants:
            n = len(skus)
            code = f"AH-{family.code}-{f_no:04d}-{VARIANT_CODES[variant]}"
            if supplier.item_prefix:
                seq = next_code.get(supplier.code, rng.randint(1000, 2400))
                next_code[supplier.code] = seq + rng.randint(3, 40)
            else:  # bare numbers starting at 101: these collide across factories
                seq = next_code.get(supplier.code, 101)
                next_code[supplier.code] = seq + 1
            shopify_sku = code
            if rng.random() < 0.1:  # someone reformatted it in the Shopify admin
                shopify_sku = rng.choice([code.lower(), f"AH-{family.code}-{f_no}-{VARIANT_CODES[variant]}",
                                          code.replace("-", "")])
            roll, client_sku = rng.random(), code
            if roll < 0.10:
                client_sku = ""
            elif roll < 0.15:
                client_sku = code[:-2] + code[-1] + code[-2]
            launched = family.launches.get(variant)
            listed_on_amazon = on_amazon or launched is not None and family.code == "LID"
            skus.append(Sku(
                code=code, family=family, variant=variant, supplier=supplier,
                upc=ids.upc_a(UPC_PREFIX, n + 10),
                factory_code=f"{supplier.item_prefix}{seq}",
                tpl_item_code=f"ACMH-{10021 + 7 * n}", tpl_client_sku=client_sku,
                shopify_product_id=product_id, shopify_variant_id=44_120_000_000_000 + rng.randint(10**6, 10**9),
                shopify_variant_sku=shopify_sku,
                amazon_seller_sku=(code + "-FBA" if rng.random() < 0.3 else code) if listed_on_amazon else None,
                asin=ids.asin(rng) if listed_on_amazon else None,
                fnsku=ids.fnsku(rng) if listed_on_amazon else None,
                popularity=rng.paretovariate(1.5), launched=launched,
            ))
    return skus


CNY_PRICE_LIST_RATE = Decimal("7.20")  # CNY suppliers fixed their 2026 price lists at this rate


def unit_price(sku: Sku, on: date) -> Decimal:
    """The supplier's price for a SKU on a date, in the supplier's currency, after announced changes."""
    price = sku.family.cost_usd * (CNY_PRICE_LIST_RATE if sku.supplier.currency == "CNY" else 1)
    for change in sku.supplier.price_changes:
        if on >= change.effective:
            price *= 1 + change.percent / 100
    return price.quantize(Decimal("0.01"))
