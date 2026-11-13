# FirstSync

**Claude gets a new customer's Salesforce data live in your product. A person approves before anything is written.**

When a B2B company signs an enterprise customer, go-live stalls for weeks on integration
work: checking permissions, mapping custom fields, migrating history, setting up sync.
A support engineer usually does that by hand. FirstSync gives the work to Claude, which
inspects the customer's org, proposes how each field maps, and explains every failure in
plain language. Deterministic code decides what actually runs.

> **Status: week 1 of 6.** The read tools, masking, audit log, target schema and two
> synthetic test orgs are built and tested. Mapping, dry-run, approval, migration and sync
> are not built yet. This is a reference implementation with no customers. See
> [What is and is not tested](#what-is-and-is-not-tested).

## The rule the design is built on

Claude proposes; the system authorizes.

- Every tool Claude has is read-only or produces a proposal. Nothing it can call writes
  to Salesforce or to the target.
- Tools take a connection handle such as `org_b`. Claude never sees a credential.
- Sampled records are masked before they reach the model.
- Every tool call is logged with a hash of what it returned.

The full design is in [docs/SPEC.md](docs/SPEC.md).

## What works today

Five tools, served from one MCP server:

| Tool | Returns |
| --- | --- |
| `sf_check_access` | Objects the connected user can read, and the fix for any that are missing |
| `sf_describe_object` | Fields, types, required flags and picklist values for one object |
| `sf_count_records` | Record counts per object |
| `sf_sample_records` | Up to 50 masked records, with the masking applied to each field |
| `target_get_schema` | The target app's tables, fields, allowed values and required fields |

Two synthetic Salesforce orgs with answer keys:

| Org | Theme | What is planted |
| --- | --- | --- |
| A | Clean baseline | Nothing. Standard objects and fields. |
| B | Renamed and custom | `Field_7__c` holding the industry, `Account.Site` holding a date as text, `Contact.Department` holding the buying role, a custom `Deal__c` object in place of Opportunity, and a `Legal Hold` stage with no match in the target |

All data is invented and every email uses the reserved `.example` domain.

## Quick start

Needs Python 3.11 or later. Use a virtual environment; Homebrew and most Linux system
Pythons refuse installs outside one.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                       # 53 tests, no network, no API key
python -m firstsync.mcp_server  # the MCP server, over stdio
```

Ask Claude to inspect org B using only those tools:

```bash
pip install -e ".[agent]"
export ANTHROPIC_API_KEY=...
python scripts/describe_org.py org_b
```

Regenerate the test orgs (the output is deterministic, and a test checks it):

```bash
python scripts/seed_org.py
```

## How masking works

The model needs to see what a field looks like, not what it contains.

| Field kind | Treatment | Example |
| --- | --- | --- |
| Ids, numbers, dates, booleans, picklists | Passed through | `T1`, `2026-03-14` |
| Names, emails, phones, URLs, addresses | Shape kept, content dropped | `(512) 555-0142` becomes `(999) 999-9999` |
| Long text | Length only | `[text, 212 chars]` |
| Text with a few repeating values | Passed through as a hand-typed picklist | `Retail`, `Energy` |
| Anything not in the describe result | Dropped | |

The fourth row matters: a custom text field that holds six industry names is exactly what
a mapping has to be built on, so those values are kept. A text field whose values look
like emails is never treated that way.

## What is and is not tested

| Part | Tested how |
| --- | --- |
| Tools, masking, audit log, fixtures, answer keys | Unit tests, offline |
| MCP server | Unit tests, plus a real MCP client over stdio |
| Salesforce REST client | Against mocked HTTP only. **Not yet run against a live org.** |
| Live loader (`seed_org.py --live`) | Against mocked HTTP only. **Not yet run against a live org.** |
| Org B metadata (`orgs/org_b/salesforce`) | XML is well formed. **Not yet deployed to a live org.** |
| `scripts/describe_org.py` | **Not yet run.** It needs an API key. |

## Loading a test org into Salesforce

For a free Developer Edition org you own. Org B needs its custom fields first:

```bash
cd orgs/org_b/salesforce
sf org login web --alias firstsync-b
sf project deploy start --target-org firstsync-b
sf org assign permset --name FirstSync_Seed --target-org firstsync-b
cd ../../..

export SF_INSTANCE_URL=...   # from: sf org display --target-org firstsync-b
export SF_ACCESS_TOKEN=...
python scripts/seed_org.py --org org_b --live
```

The loader is developer tooling. It is the only code here that writes to Salesforce, and
it is not reachable from the MCP server.

## Roadmap

| Week | Deliverable |
| --- | --- |
| 1 | Read tools, masking, audit log, orgs A and B **(this)** |
| 2 | Discover and map stages, rule validator, orgs C, D and E, mapping accuracy eval |
| 3 | Dry-run engine, diff, failure grouping |
| 4 | Admin screens, approval gate, migration into the target sandbox |
| 5 | Change Data Capture sync, retry queue, go-live report |
| 6 | Hosting, held-out run on org E, published results |

## Licence

Apache-2.0.
