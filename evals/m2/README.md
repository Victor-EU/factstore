# M2 exit: a fresh agent with only the MCP server

The build plan's last M2 exit test reads: "A fresh agent given only the MCP server, with no extra prompt, answers the ten questions and ingests a further fixture sample using the attributes already registered, without forcing a near-duplicate through `distinct_from`. Each failure is fixed in the tool descriptions, not with hints in the prompt."

## How it runs

[fresh_agent.py](fresh_agent.py) runs `claude -p` in an empty directory:
- the `factstore` MCP server is its only tool (`--tools ""`, `--strict-mcp-config`);
- no project files and no other instructions;
- the store is the default fixture world, freshly loaded, with a new actor for the agent so its writes can be told apart.

There are two parts:

- **Questions.** The prompt is the ten questions, the date, and the JSON format for the answers. They are scored against the naive fold over the log.
- **Ingestion.** The prompt is [sample.md](sample.md): a buyer's note and a proforma invoice for a new PO, a WeChat slip in Chinese, an inspection report, and a forwarder's booking amendment. The run is scored on four things:
  - the 46 facts the sample should leave in the store;
  - attributes registered;
  - attributes forced through `distinct_from`;
  - whether the amended booking left any PO line on two shipments.

Transcripts of every tool call are in `results/*.stream.jsonl`.

## Results

| Run | Questions | Ingestion facts | New attributes | Forced via `distinct_from` | Booked twice |
|---|---|---|---|---|---|
| **Sonnet, final kernel** | **10/10** | **46/46** | **0** | **0** | **no** |
| Sonnet, first descriptions | 10/10 | 46/46 | 0 | 0 | no |
| Haiku, first descriptions | 7/10 | 42/46 | 3 | 0 | yes |
| Haiku, after fixes 1–2 | 10/10 | 19/46 | 6 | 2 | yes |
| Haiku, after fix 3 | | 44/46 | 4 | 1 | yes |

On the final kernel, Sonnet took 14 turns and $0.13 for the questions, and 16 turns and $0.16 for the ingestion.

**The exit test passes with Sonnet.** It needed no fixes. In its first ingestion, the booking amendment looked like a new booking because the sample didn't say it replaced one. Sonnet found the existing booking for the same HBL anyway, re-keyed it and its four lines in one transaction, and asked a human to confirm. The sample now says it replaces the old booking.

**Haiku found these problems, and the fixes made from them:**

1. **A new version of a value was registered as a new attribute.** Haiku recorded a supplier's slip as `po/revised_etd`. The kernel's near-match check missed it, because trigram similarity between `poetd` and `porevisedetd` is low.
   - *Kernel:* a new name in the same namespace whose words contain an existing name's words (or the reverse) is now a near match. The fixture's 93-attribute vocabulary gains no new refusals.
   - *Descriptions:* `transact` and `register_attribute` now say a changed value is a new assertion on the same attribute, never a new attribute.
2. **Query mistakes.** One join fan-out doubled a sum (Q1). A history question came back empty (Q2). A duplicate chain was followed one way only (Q8). The `query` description now warns that joins multiply rows and shows how to read a value's history. Haiku then got all ten right.
3. **`distinct_from` used to get past a refusal.** Haiku put the proforma invoice on the shipment as `shipment/pi_number`. Registration was refused as a match for `po/pi_number`, so it reworded the doc and declared them distinct.
   - *Refusals* now come back with what to do next: reuse a match if its doc fits, putting the value on the entity it describes.
   - *The `register_attribute` description* now says that `distinct_from` means "different meaning", not "same value on another entity".

**What Haiku still gets wrong:**
- **Booking twice.** It records the amended booking as a new shipment and leaves the old one, so the cargo is booked twice.
- **Extra attributes.** It registers attributes for details the vocabulary doesn't cover: the PI's total, its date, its payment terms, and a raw WeChat message.

Neither is a tool-description problem. They are modelling choices that belong to the ingestion skill (M4), and the second is M5's "attributes registered beyond the package" measure.

## Reproduce

```bash
cd evals/m2
../../factstore/.venv/bin/python fresh_agent.py --model sonnet --part both
```

Each part loads the default world into its own store (`fs_m2_questions`, `fs_m2_ingest`) and leaves it there for inspection.
