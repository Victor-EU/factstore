"""The rounds of build plan M6: one use case on one public dataset each (README).

A round is fixed before it runs: the use case, where its data comes from and under what licence,
which stages run, which columns hold each kind of record's ID, and the questions someone with that
use case would ask, with their answers computed from the raw files. The columns and questions are
written when the round starts, once its data is in place, since they name the files' columns.

Data lives in data/<dataset>/ at the repo root, which git ignores. Each folder in `sources` is
copied, read-only, into the agent's ./exports.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import round1
import round2
import round3
import round5


@dataclass(frozen=True)
class Ids:
    """A column holding one kind of record's ID. Its distinct values are what the store should
    index (the catalogue's step 7 counts check)."""
    kind: str
    file: str  # a glob under the dataset's folder, starting with a source: "shop/*.csv"
    column: str


@dataclass(frozen=True)
class Round:
    number: int
    use_case: str
    dataset: str
    origin: str
    licence: str
    stages: tuple[str, ...]
    packages: tuple[str, ...]  # repo paths, installed after core
    sources: tuple[str, ...]
    prompts: dict[str, str]
    sizes: str  # how much of the data each pass gets
    ingest_skill: str | None = None
    ids: tuple[Ids, ...] = ()
    personal: tuple[tuple[str, str], ...] = ()  # (file glob, column), as for Ids: values that must never reach the store
    questions: tuple[dict, ...] = ()  # {"id", "text", "columns"}
    answers: Callable[[Path], dict[int, list]] | None = None  # from a folder holding the sources
    truth: Callable[[object, Path], dict] | None = None  # what the dataset itself says is right
    sampler: Callable[[Path, Path, int], None] | None = None  # (dataset, exports, n); else the first n rows
    judge: Callable[[list, list], bool] | None = None  # (given rows, expected rows); else M5's exact match
    notes: tuple[str, ...] = field(default=())


ECOM = ("packages/ecom-ops", "packages/ecom-index", "factstore-skills")

CATALOGUE = "{what} Catalogue them into the fact store with the factstore-catalogue skill."

ROUNDS = {r.number: r for r in [
    Round(
        1, "One product list across the marketplaces a brand sells on",
        dataset="ecommerce-sales-india",
        origin="https://www.kaggle.com/datasets/thedevastator/unlock-profits-with-e-commerce-sales-data "
               "(7 CSVs, 6.6 MB zipped; unzip into data/ecommerce-sales-india/reports/)",
        licence="Kaggle 'other', no terms stated; a re-upload of data.world/anilsharma87. "
                "Internal testing only (Victor, 2026-10-02).",
        stages=("catalogue", "rerun", "questions"), packages=ECOM, sources=("reports",),
        prompts={"catalogue": CATALOGUE.format(what=(
            "Our sales and stock reports, from the marketplaces we sell on and our warehouse, are "
            "exported in ./exports/reports."))},
        sizes="all of it; a trial on 40 product styles, with every row that names them",
        ids=(Ids("Amazon order", round1.AMAZON, "Order ID"), Ids("ASIN", round1.AMAZON, "ASIN"),
             Ids("Amazon seller SKU", round1.AMAZON, "SKU"), Ids("stock report SKU", round1.STOCK, "SKU Code"),
             Ids("international SKU", round1.INTERNATIONAL, "SKU"), Ids("price list SKU", round1.PRICE_LISTS[0], "Sku")),
        personal=((round1.INTERNATIONAL, "CUSTOMER"),),
        questions=round1.QUESTIONS, answers=round1.answers, truth=round1.truth, sampler=round1.sample,
        notes=("Pass: all six questions; every plain ASIN on its own code; both listings under each ASIN "
               "listed under two codes; no product split by its spellings; no #REF!, blank or size range as "
               "a code; no price-list code linked to another product; no customer name in the store; the "
               "re-run writes nothing.",
               "Runs a and b were on ecom-ops 0.3.0, where an ASIN sat on one product. Victor chose B: a "
               "listing is a record of its own (ecom-ops 0.4.0, 2026-10-02).")),
    Round(
        2, "One shop's orders, customers and products, with real junk in its ID columns",
        dataset="online-retail-ii",
        origin="https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci "
               "(1 CSV, 95 MB; into data/online-retail-ii/shop/). The original is UCI dataset 502.",
        licence="CC0 on Kaggle; the UCI original is CC BY 4.0 (Daqing Chen).",
        stages=("catalogue", "rerun", "questions"), packages=ECOM, sources=("shop",),
        prompts={"catalogue": CATALOGUE.format(what=(
            "Our online shop's order lines from December 2009 to December 2011 are exported in "
            "./exports/shop."))},
        sizes="all of it; a trial on 300 customers' invoices, 300 with no customer, and every junk code's",
        ids=(Ids("invoice", round2.FILE, "Invoice"), Ids("stock code", round2.FILE, "StockCode"),
             Ids("customer, as the file writes it", round2.FILE, "Customer ID")),
        questions=round2.QUESTIONS, answers=round2.answers, truth=round2.truth, sampler=round2.sample,
        notes=("Pass: all six questions; every customer in the store, none as a decimal; every invoice but "
               "the six bad-debt adjustments, each that names a customer pointing at it; every product, none "
               "split by its case; no code that isn't a product as a product; no line keyed by its row's "
               "position, so no more lines than invoice-and-product pairs; no ID on another system's attribute, "
               "such as Shopify's; the re-run writes nothing.",
               "The shop has no package, so the catalogue registers its identifiers: reported, not failed.",
               "Gift vouchers, and PADS (pads sold with cushions), are products or not by judgement: reported.")),
    Round(
        3, "A marketplace at scale, with a second dataset joined in and duplicate customers",
        dataset="olist",
        origin="https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (9 CSVs, into "
               "data/olist/marketplace/) and https://www.kaggle.com/datasets/olistbr/marketing-funnel-olist "
               "(2 CSVs, into data/olist/funnel/)",
        licence="CC BY-NC-SA 4.0. Non-commercial use; factstore is MIT-licensed and not sold.",
        stages=("catalogue", "rerun", "ontology", "questions"), packages=ECOM,
        sources=("marketplace", "funnel"),
        prompts={"catalogue": CATALOGUE.format(what=(
            "We run a marketplace. Its orders, customers, sellers, products, payments and reviews are "
            "exported in ./exports/marketplace, and our sales team's funnel of sellers who asked to "
            "join in ./exports/funnel."))},
        sizes="all of it; a trial on 100 people with several customer IDs, 100 other orders and the "
              "questions' cases, with every row that names them",
        ids=(Ids("order", round3.ORDERS, "order_id"), Ids("customer", round3.CUSTOMERS, "customer_id"),
             Ids("product", round3.PRODUCTS, "product_id"), Ids("seller", round3.SELLERS, "seller_id"),
             Ids("closed seller", round3.DEALS, "seller_id"), Ids("lead", round3.LEADS, "mql_id")),
        personal=((round3.REVIEWS, "review_comment_message"), (round3.REVIEWS, "review_comment_title")),
        questions=round3.QUESTIONS, answers=round3.answers, truth=round3.truth, sampler=round3.sample,
        notes=("Pass: all seven questions; every customer, order, product, seller (the funnel's too) and lead "
               "in the store; each person's customer IDs joined, and no two people joined; every order "
               "pointing at its customer; one item per item number the source gives, each pointing at its "
               "product and seller; every review on each of its orders; each closed seller linked to its "
               "lead; no ID on another system's attributes; no postcode or category taken for a record; no "
               "review comment in the store; the re-run writes nothing.",
               "customer_unique_id says which customer IDs are one person: the duplicates' answer key.",
               "The funnel joins the marketplace by seller_id. Payments, and the ontology's shapes, are "
               "reported: nothing says how either should look.")),
    Round(
        4, "Read supplier invoices and orders",
        dataset="docile",
        origin="https://github.com/rossumai/docile: the annotated set, with a token from "
               "https://docile.rossum.ai (into data/docile/documents/)",
        licence="The terms given with the token; read them before downloading.",
        stages=("ingest", "rerun", "questions"), packages=("packages/ecom-ops", "factstore-skills"),
        sources=("documents",), ingest_skill="packages/ecom-ops/ingest-documents",
        prompts={"ingest": "Our suppliers' invoices and orders are in ./exports/documents. Ingest them into "
                           "the fact store with the ecom-ops-ingest-documents skill."},
        sizes="20 documents, then 100, then 500, each only once the smaller passes",
        notes=("MIDD was the first choice; its public files hold only the annotations, not the PDFs.",
               "The annotations give each document's fields and line items: the answer key.")),
    Round(
        5, "One mailbox in another industry, with no vocabulary package",
        dataset="enron",
        origin="https://huggingface.co/datasets/intellekthq/enron-ferc-pst: one custodian's PST "
               "(11 MB to 2.1 GB each; into data/enron/mailbox/). Reading it needs libpst's readpst.",
        licence="CC BY 3.0 US. Credit ZL Technologies; a modified version of the EDRM Enron corpus.",
        stages=("ingest", "rerun", "ontology", "questions"), packages=("factstore-skills",), sources=("mailbox",),
        ingest_skill="factstore-skills/ingest",
        prompts={"ingest": "One of our gas traders' mailboxes, from 2000 and 2001, is exported in ./exports/mailbox: "
                           "one file per message, in the folders the mail client kept. Record what it says in the "
                           "fact store with the factstore-ingest skill, so that we can look it up later."},
        sizes="custodian south-s: 103 messages in 249 files, all of it; a trial on 30 messages and the "
              "questions' 8, with every copy. Then a larger custodian, for 1,000.",
        questions=tuple({k: v for k, v in q.items() if k != "source"} for q in round5.QUESTIONS),
        answers=round5.answers, truth=round5.truth, sampler=round5.sample, judge=round5.judge,
        notes=("Pass: all eight questions whose message the agent was given; each message recorded once, "
               "with its issue date, whichever folders hold it; every fact citing the message it came from; "
               "no person's name, address or phone number in the store; 50 facts drawn at random all saying "
               "what their message says (checked by hand); the re-run writes nothing.",
               "Runs t to c had no ingestion skill, only the store's tool descriptions; from run b the store's "
               "instructions state its rules. From run d, the general factstore-ingest skill (Victor, 2026-10-03). "
               "The ontology stage has its skill, as in every round.",
               "custodian south-s: data/enron/raw/zl_south-s_000.pst, 10.9 MB, sha256 852f2090…, read with "
               "readpst -e into data/enron/mailbox/.")),
]}
