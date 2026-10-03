---
name: factstore-ingest
description: Read documents into a factstore when no vocabulary package covers their business, every fact backed by the document it came from. Covers emails and mailboxes, chat exports, PDFs and office files, in any industry. Use when asked to ingest, extract, read in or record what a mailbox or a folder of documents says, and no package's own ingestion skill fits.
---

# Read documents into the store, with no package

A mailbox or a folder of documents states things a business looks up later: a deal's number and price, a notice's effective dates, a deadline, a quantity, a decision. This skill turns them into facts, each pointing at the document that states it. With no package, you name the kinds of record and their attributes yourself.

If a package's own ingestion skill covers these documents, such as ecom-ops-ingest-documents for supplier and logistics documents, use that skill instead.

You need the factstore MCP tools, and a shell with Python for hashing, parsing mail (`email`) and reading PDFs (`pypdf`).

## Rules

1. **Record what a document states, as values.** Identifiers, dates, quantities, prices, statuses and decisions, and the refs between records. Not copies of text: a body, a subject line, a summary or a note stays in the document.
2. **No personal data.** A person's name, email address, phone number and postal address stay in the document, and so do the sender and recipients. A person is never a record, a key or a value. Organisations are records: a company, a counterparty, a supplier, an agency.
   - The one exception is an attribute the business that owns the store has allowed for personal data. The store's instructions show how to list them, and there are usually none. Fill one only as a document states it.
   - Never allow an attribute yourself.
3. **Every fact cites the document that states it.** Put the document in each transaction:
   ```json
   {"e": "tmp:tx", "a": "core/evidence", "v": ["document/hash", "<sha256 hex>"]}
   ```
   A fact cites only a document whose text states it. A fact you put together from two documents goes in two transactions, one for each part, or is left out. What you know from other mail, or from outside the mailbox, is not stated.
4. **Say how sure you are.** A value the document prints plainly: `core/confidence` "1". A value you had to interpret, such as a date written without its year or a record named loosely, goes in its own transaction at the confidence you have.
5. **A document in the store has been read.** Record every document you read, even one that states nothing, so that the next run knows it. Read again only the documents the store lacks, unless asked. Address every record by its key, so that reading a document twice writes nothing.

## Documents

Each document is an entity with `document/hash`, `document/url` and `document/issued_at`:
- the hash is the SHA-256 of the file's bytes, hex;
- the url is its path under the export folder, or `mid:<Message-ID>` for an email;
- the issue date is when it was sent or dated, as an instant: an email's `Date` header, a chat message's timestamp, the date printed on a PDF.

**Copies are one document.** A mail client keeps one message in several folders, and an export gives each copy a file of its own, often with its own Message-ID. Messages with the same date, sender, subject and body are copies.
- Record one document for them: hash the first copy by path, and give its path as the url.
- Write the other copies' paths nowhere. The folders a message sat in are not facts.

**A date that can't be right is left out.** Drafts and unsent mail often carry a placeholder date, such as one later than every other message. Record the document without an issue date, and say so in your report.

## Working through a mailbox or a folder

1. **List the documents.** Extract each one's text, issue date, hash and url into your working directory, and group the copies. Read the attachments you can open: text, PDF, RTF, Word and spreadsheet files. List the ones you can't.
2. **Read every document, and keep what states something about the business.**
   - Mail sent to many is still read. A notice, a bulletin or a solicitation from another company carries numbers, dates and deadlines.
   - Skip a document only when it states nothing a person running the business would look up, such as social mail and company-wide announcements.
3. **List the values each document states,** in a table in your working directory: the document, the record the value belongs to, the field, and the value as written. Look for:
   - identifiers: deal, contract, order, invoice, notice, case and report numbers;
   - dates: effective, start and end, due, closing, delivery and payment dates;
   - quantities and prices, with their units and currency;
   - statuses and decisions: approved, cancelled, placed on hold, lowered to, moved to.

   A value belongs in the store when the document states it, whether or not an attribute exists for it yet.
4. **Group the values into kinds of record,** such as a deal, a notice or a claim, and give each record a key:
   - its own identifier, when the document gives one: a deal number, a notice number;
   - otherwise a key built from what makes it unique, such as the company, the place and the start date: `acme/rotterdam/2001-04-26`. Never a person, and never a document's position in the folder.
   - an organisation is keyed by its name, spelled as the documents most often spell it: one record, however many documents name it.
5. **Register the attributes, in one batch.**
   - Search for each one first, and reuse an attribute whose doc fits.
   - Name a new one after the kind of record and the field: `notice/effective_from`, `deal/price`. One namespace per kind of record.
   - Pick the type that holds the value: `decimal` for quantities and prices, with the unit in the name or the doc (`shipment/weight_kg`); `date` for days; `instant` for a moment with a time and time zone; `string` for identifiers and names; `ref` from a record to another.
   - Write a doc that says what the value is, on which record, and whose it is.
   - An identity attribute holds each kind's key, so lookups find the record again.
6. **Write one document at a time, in issue order.** A later document's value lands after an earlier one's, since the last assertion wins. A changed value is a new assertion on the same attribute, never a new attribute.
   - Facts from one document go in one transaction, with its evidence and confidence. Interpreted values go in a second one.
   - Create each document in the same transaction as its first facts, or on its own when it states nothing.
   - For more than a few hundred facts, write a script that uses the SDK (`import factstore`; `factstore.transact(facts)`, with the store in `FACTSTORE_DSN`). Run it on a few documents, and check the result with `query` before running the rest.
7. **Where documents disagree, or one doubts itself,** record what each states, each citing its own document, and report the conflict. Don't pick a winner.

## Check what you wrote

- **Documents.** The store holds one document for each distinct message or file, and each has an issue date unless you reported why not.
- **Evidence.** Every transaction you wrote carries `core/evidence`.
- **No personal data.** List the string values you wrote, and look for names, email addresses and phone numbers outside the attributes the business allowed.
- **Ten facts against their documents.** Draw ten facts, read each one's document, and check that it states them. If any doesn't, find what wrote it and fix the rule.

## Finish with a report

- Documents read, the copies grouped, and those skipped, with why.
- The kinds of record you made, with their keys and counts, and the attributes you registered.
- Facts at confidence below 1, and why.
- Conflicts between documents, and attachments you couldn't read.
