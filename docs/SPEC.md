# FirstSync specification

Version 1 scope: one source (Salesforce), one target (a small reference customer-success
app with accounts, contacts, deals and activities), end to end: connect, preflight, map,
dry-run, approve, migrate, ongoing sync. HubSpot, Slack and single sign-on are out of scope.

> **Status: feature-complete (six-week build).** Every stage below is built and tested.
> What this document once marked "planned" either shipped or, in several cases, shipped as
> a human CLI command rather than a tool the model can call — a deliberate strengthening of
> principle 3. The one external dependency not exercised is a live Salesforce org; the REST
> client and loader run against mocked HTTP only. The remaining roadmap item is a hosted
> portal, not core logic.

## Design principles

1. **Claude investigates freely and writes nothing.** Every tool is read-only or produces
   a proposal. No tool writes to Salesforce or to the target.
2. **Proposals are data, not code.** Mappings and transformation rules use a restricted
   format that a deterministic engine validates and runs.
3. **A human approves before the first write.** Approval, migration and sync are command-
   line actions a person takes; none is a tool the model can call. Approval binds to a
   hash of what was approved, so a proposal changed afterwards invalidates it.
4. **Every claim links to evidence.** Each mapping, explanation and report line points to
   the schema field, sample record or log entry behind it.
5. **Claude never sees credentials or raw personal data.**
6. **Results are measured, not asserted.**

## Claude's role at each stage

| Stage | What Claude does | What the system enforces |
| --- | --- | --- |
| 1. Connect | Checks what the connected user can read; names the permission to change | OAuth handled outside the model |
| 2. Discover | Reads the schema and masked samples to work out what each field holds | Samples capped at 50 and masked |
| 3. Map | Proposes each mapping with a reason, a confidence level and a rule | Rules validated before they are stored |
| 4. Dry-run | Nothing — the engine builds every record and groups failures by root cause | Deterministic code; duplicates flagged by natural key; nothing written |
| 5. Approve | Nothing — a person approves at the CLI | Approval is hash-bound; the model cannot approve |
| 6. Migrate | Nothing — the engine upserts approved records | Runs only behind approval; idempotent on `(tenant, external_id)` |
| 7. Sync | Nothing — the engine re-reads and applies the delta | Adds and updates only; regressed and vanished records are reported, never acted on |
| 8. Hand-off | Explains results through read-only status tools | The go-live report and `trace` read state the engines wrote |

The row builder used by the dry-run is the same code the migration and sync use, so what
an administrator previews is exactly what loads.

**Ongoing sync.** The reference implementation detects change by re-reading the source and
comparing each rebuilt row against what is already loaded: new records are inserted,
changed ones updated, and records that regressed (were live, now fail validation) or
vanished (gone from the source) are reported for a person to decide. Salesforce Change
Data Capture — streaming change events — is the production path and is noted, not built,
for the same reason the live REST client is not exercised here.

## Tools

All read-only or proposal-producing. Built:

- Discovery (week 1): `sf_check_access`, `sf_describe_object`, `sf_count_records`,
  `sf_sample_records`, `target_get_schema`
- Mapping (week 2): `rule_test`, `mapping_propose`
- Dry-run (week 3): `dryrun_start`, `dryrun_get_results`
- Status, read-only (weeks 4–5): `migration_get_status`, `sync_get_status`

What the original plan listed as `approval_request`, `sync_propose_fix` and `report_write`
deliberately did **not** become tools. Approving, migrating, syncing and writing the
report are human CLI commands (`firstsync approve | migrate | sync | report`), so the model
has no path to authorize or trigger a write. `firstsync trace` gives a reviewer a view over
the audit log; it too is not a tool the model can call.

Deliberately never exposed to the model: any write to Salesforce or the target, token
access, granting approval, starting a migration or sync.

## Mapping and rule format

One JSON record per target field. A rule may use only these eleven operations: `copy`,
`trim`, `case`, `cast`, `parse_date`, `map_values`, `lookup`, `split`, `concat`, `default`,
`normalize_phone`.

`normalize_phone` was added in week 2. The original ten operations could not turn a phone
number into the E.164 format the target requires.

```json
{
  "target": "deals.stage",
  "source": "Deal__c.Deal_Phase__c",
  "confidence": "medium",
  "reason": "Custom picklist with 7 values; 6 match target stages by meaning. 'Legal Hold' has no match.",
  "evidence": ["describe:Deal__c.Deal_Phase__c", "sample:Deal__c#1-50"],
  "rule": [
    {"op": "trim"},
    {"op": "map_values",
     "table": {"Prospect": "lead", "Qualified": "qualified", "Proposal Sent": "proposal",
               "Negotiating": "negotiation", "Won": "closed_won", "Lost": "closed_lost"},
     "unmapped": "ask_admin"}
  ],
  "question_for_admin": "Some deals are in 'Legal Hold'. Which stage should they land in?"
}
```

High confidence is accepted by default. Low confidence requires a question to the admin
before the mapping can be approved. A required target field needs a mapping or an explicit
default before approval can be requested. From week 3, the dry-run scores a rule by its
effect on real records, not just whether the source field was chosen — so a mapping that
picks the right field but a wrong transformation shows up as failing records.

## Test orgs and evaluation

| Org | Theme | Status |
| --- | --- | --- |
| A | Clean baseline | Built |
| B | Renamed and custom | Built |
| C | Picklist drift | Built |
| D | Dirty data, including a record that tries to instruct the model | Built |
| E | Locked down, held out from prompt tuning | Built; run once (below) |
| F | Decoys: two plausible sources for one target, where the better-named one is wrong | Built |

Each org has an answer key: the correct source for every target field, including the
fields that should be left unmapped and the fields where the only correct behaviour is to
ask the administrator. Org D's key also lists the planted data defects, and the dry-run is
scored on whether it catches them.

**Measured results** (not targets):

- Source accuracy, three runs each on A, B, C, D, F: `claude-sonnet-5-5` 435/435 (100%);
  `claude-haiku-5-5` 430/435 (98.9%), at roughly a twelfth of the cost.
- Dry-run defect detection on org D: 4/4 planted defect classes caught (missing emails,
  missing amounts, short phones, duplicate contacts), for both models.
- **Held-out org E, run once, never tuned against: 29/29 (100%), with 9 questions asked for
  exactly the 9 the key required and 0 extra, ~$0.12 per run.** This is the one accuracy
  figure measured on an org the prompt had never seen. It is a single run; the tuned orgs
  were three each.

"Accuracy" scores the source field and whether a required question was asked; the dry-run
adds the separate check that the rule produces loadable data. The prompt was revised once
and the answer keys twice, on the tuned orgs only, before org E was ever run. Full history:
[docs/week2-first-eval.md](week2-first-eval.md).

## Security and data handling

- Tokens stay in the backend; tools receive a connection handle.
- The Salesforce connection is read-only.
- Sampled records are masked before they reach Claude.
- Every target row carries a tenant id, derived deterministically from the connection
  handle; reads and writes are scoped to it, and the key `(tenant_id, external_id)` keeps
  tenants isolated and migrations idempotent. The target is SQLite by default (so tests and
  CI need no services); the DDL is generated from the one target schema, and Postgres —
  with row-level security — is the production option.
- Every tool call is logged with a hash of what it returned; `firstsync trace` reads that
  log back per session. A record the dry-run engine cannot process is written to a
  dead-letter file and counted, never silently dropped.
- Field names, labels and record values are treated as data. Instructions found inside
  them are ignored. Org D plants one in a field that survives masking, and the evaluation
  reports whether it was followed (neither model followed it).
- Per-session caps: 300 tool calls on the server, 50 sampled records per object, and a
  model spend limit per agent run.
