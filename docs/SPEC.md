# FirstSync specification

Version 1 scope: one source (Salesforce), one target (a small reference customer-success
app with accounts, contacts, deals and activities), end to end: connect, preflight, map,
dry-run, approve, migrate, ongoing sync. HubSpot, Slack and single sign-on are out of scope.

## Design principles

1. **Claude investigates freely and writes nothing.** Every tool is read-only or produces
   a proposal. No tool writes to Salesforce or to the target.
2. **Proposals are data, not code.** Mappings and transformation rules use a restricted
   format that a deterministic engine validates and runs.
3. **A human approves before the first write.** Claude can request approval and cannot
   grant it.
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
| 4. Dry-run | Groups failures into root causes and proposes a fix per cause | First 50 records per object; nothing written |
| 5. Approve | Answers the admin's questions from logged results | Only a logged-in admin can approve |
| 6. Migrate and sync | Triages failed records in the retry queue | The engine runs writes; rule changes return to approval |
| 7. Hand-off | Writes the go-live report | Every line links to a log entry |

Ongoing sync uses Salesforce Change Data Capture.

## Tools

Built in week 1: `sf_check_access`, `sf_describe_object`, `sf_count_records`,
`sf_sample_records`, `target_get_schema`.

Planned: `rule_test`, `mapping_propose`, `dryrun_start`, `dryrun_get_results`,
`approval_request`, `sync_get_failures`, `sync_propose_fix`, `report_write`.

Deliberately never exposed: any write to Salesforce or the target, token access, granting
approval, starting a migration.

## Mapping and rule format (week 2)

One JSON record per target field. A rule may use only these operations: `copy`, `trim`,
`case`, `cast`, `parse_date`, `map_values`, `split`, `concat`, `default`, `lookup`.

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
default before approval can be requested.

## Test orgs and evaluation

| Org | Theme | Status |
| --- | --- | --- |
| A | Clean baseline | Built |
| B | Renamed and custom | Built |
| C | Picklist drift | Week 2 |
| D | Dirty data | Week 2 |
| E | Locked down, held out from prompt tuning | Week 2 |

Each org has an answer key: the correct source for every target field, including the
fields that should be left unmapped.

Metrics to publish (targets are goals, not results): mapping accuracy (90% or higher),
override rate (under 15%), planted blocking defects caught before write (all), false
alarms (under 5% of flags), minutes from connect to first synced record, and model cost
per onboarding on a small and a large Claude model.

## Security and data handling

- Tokens stay in the backend; tools receive a connection handle.
- The Salesforce connection is read-only.
- Sampled records are masked before they reach Claude.
- Every table carries a tenant id, enforced with Postgres row-level security (week 4).
- Field names, labels and record values are treated as data. Instructions found inside
  them are ignored, and the evaluation includes a record that tries this (week 2).
- Per-session caps on tool calls, sampled records and model spend (week 2).
