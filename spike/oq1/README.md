# Open question 1: the query language spike

Build plan M0 says the spike decides the query language: write a one-page doc for each candidate, have models answer the ten questions from that doc alone, and score them against hand-written references. The candidate models get right most often wins.

## Method

**The questions** ([questions.py](questions.py)) are an operator's questions about the default fixture world (seed 7, scale 1: 364k facts, 699 transactions). They are about the supply side, which the store is primary for. Between them they need:
- ref traversal in both directions;
- grouping and sums;
- arithmetic;
- a ref followed through several hops (`core/same_as`);
- an as-of read;
- the log's history ("the ETD first recorded");
- the transaction stamps ("who recorded this, and when").

**Reference answers** come from a deliberately naive fold over the log, the M1 test oracle, not from any candidate.

**The candidates**, each with a one-page doc in [docs/](docs) of the same shape and the same three worked examples, none overlapping the questions:
- **A. JSON patterns** ([docs/json.md](docs/json.md)): nested entity patterns, `^` for reverse refs, `*`/`+` for transitive refs, aggregates in `select`.
- **B. Datalog** ([docs/datalog.md](docs/datalog.md)): Datomic's syntax as EDN text, rules for recursion, five-element patterns for the log.
- **C. SQL over views** ([docs/sql.md](docs/sql.md)): one view per attribute (`"po/status"(e, v, tx)`), schema `history` for the log, `as_of` honoured by every view.

A and B compile to one naive in-memory engine ([engine.py](engine.py)). C runs on Postgres, through views ([sql_views.py](sql_views.py)) and a read-only login. Hand-written queries ([handwritten.py](handwritten.py)) answer all ten questions correctly in all three languages, so every question can be asked in every language.

**The runs.** For each language × model (Haiku 4.5, Sonnet 5.5, Opus 5.5), a fresh agent got a brief ([briefs/](briefs)) and nothing else: the doc, the store's attributes, and the questions. It ran as many queries as it liked through [run.py](run.py), a stand-in for the `query` tool that logs every call ([runs/](runs)), and wrote its answers ([answers/](answers)). An answer is right when its rows equal the reference, value by value, in any order.

A caveat on fairness: the in-memory engine behind A and B took 15–20 s a query with six agents running, against under 1 s for SQL on Postgres. The A and B agents were slower and sometimes ran a query in the background. That cost them time, not correctness.

## Results

| Agent | Right | Wrong | Queries | Errors |
|---|---|---|---|---|
| sql-haiku | 9/10 | 8 | 22 | 3 |
| sql-sonnet | 10/10 | - | 28 | 0 |
| sql-opus | 10/10 | - | 31 | 0 |
| datalog-haiku | 9/10 | 7 | 36 | 4 |
| datalog-sonnet | 10/10 | - | 24 | 0 |
| datalog-opus | 10/10 | - | 38 | 0 |
| json-haiku | 8/10 | 6, 8 | 29 | 11 |
| json-sonnet | 10/10 | - | 27 | 0 |
| json-opus | 10/10 | - | 54 | 0 |

| Language | Right | Queries | Errors |
|---|---|---|---|
| SQL | 29/30 | 81 | 3 (4%) |
| Datalog | 29/30 | 98 | 4 (4%) |
| JSON patterns | 28/30 | 110 | 11 (10%) |

Sonnet and Opus got everything right in every language. Only Haiku separates the candidates.

**The wrong answers:**
- **SQL, Haiku, Q8** (a person's orders across duplicate accounts). The recursive CTE followed `core/same_as` from the given account only, so it missed the account that points at it. It also counted orders through the wrong attribute. Recursion caused all three of Haiku's SQL errors.
- **Datalog, Haiku, Q7** (open PO value). Datomic's set semantics collapsed two order lines with the same value into one, so SZHT came out 12,232.80 instead of 21,566.88. The doc warns about this and shows `:with` in an example. The error is silent: a plausible wrong number.
- **JSON, Haiku, Q6** (crosswalk). It described the 3PL and factory codes as separate entities rather than as attributes of the SKU, joining unrelated rows, and then took `min` of the result.
- **JSON, Haiku, Q8.** It followed `core/same_as` in one direction only.

JSON-pattern errors were mostly syntax the model had to learn from the page: `where` keyed by entity, operators, `select` forms. Opus also reported that an attribute named twice in one pattern is silently dropped, because JSON keeps only the last of a repeated key.

## Decision

**SQL over views of the current-state table and the log.** SQL and Datalog tie on right answers, and JSON patterns come last on both answers and errors. The tie between SQL and Datalog breaks on what the rest of the work needs:
- **Failure mode.** Datalog's miss was a silently wrong total, from a semantic that is part of Datalog, not of our doc. SQL's miss answered 0 orders, which looks wrong on its face. A wrong number that looks right is the worse failure for a store whose pitch is "why is this number this?".
- **Friction.** SQL needed the fewest queries (81, against 98 and 110) and had the joint-lowest error rate.
- **Cost and speed.** SQL runs on Postgres as written: the views already exist, and the planner, indexes and timeouts come free. Datalog would need a compiler to SQL and its own optimizer before it could meet the 1 s budget.
- **Prior art.** XTDB, the closest prior art, moved to SQL.

Datalog is the runner-up the build plan names, if models misuse SQL in the M2 fresh-agent test.

**What the spike says the tool description needs.** Following a ref through several hops, in both directions, is where models go wrong. The `query` description should show a recursive CTE that walks a chain to its end and back again.
