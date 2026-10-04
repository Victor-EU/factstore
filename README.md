# factstore

A fact store for AI agents, on Postgres. Agents record what a company's systems and documents say as facts: a value for a registered attribute, in a transaction stamped with who wrote it and the document it came from. Nothing is overwritten, so the store can say what it knew on any date.

Skills that ship with it index a company's systems from their exports, and read documents and mail into facts. They leave people's personal details in the source. MIT-licensed.

## Install

```bash
pip install factstore
```

In Claude Code, the plugin brings the MCP server and the skills:

```
/plugin marketplace add Victor-EU/factstore
/plugin install factstore@factstore
```

[factstore/README.md](factstore/README.md#install) walks through Postgres, a first store and connecting an agent.

## What's here

| | |
|---|---|
| [`factstore/`](factstore/README.md) | The kernel, the MCP server, the Python SDK and the CLI |
| [`packages/`](packages/README.md) | Vocabulary packages: `core`, and `ecom-ops` and `ecom-index` for an online brand |
| [`factstore-skills/`](factstore-skills/README.md) | The catalogue, ontology and ingestion skills |
| [`evals/`](evals/m6/README.md) | What it was tested on: a synthetic brand, and five public datasets from real companies |
| [`factstore-design.md`](factstore-design.md) | The design, and what testing changed in it |
| [`factstore-build-plan.md`](factstore-build-plan.md) | The milestones, and where each stands |

## Status

0.1.0, alpha. The kernel's code held unchanged through every test, up to 3.2 million facts in one store. The skills passed every round on public data: product lists, a million order lines, a marketplace's duplicate customers, 100 suppliers' forms and a trader's mailbox. No company has run it on its own data yet.
