# Week 2: first evaluation run, and what it exposed

On 12 November 2026 the mapping agent ran once on each of orgs A to D with
`claude-sonnet-5-5`, mapping prompt `ca49cd77a6ac`.

## Result

| Org | Accuracy | Questions asked | Required | Allowed | Extra | Turns | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 100% (29/29) | 4 | 0 | 2 | 2 | 23 | $0.1658 |
| B | 100% (29/29) | 8 | 3 | 2 | 3 | 24 | $0.1378 |
| C | 100% (29/29) | 10 | 2 | 2 | 6 | 25 | $0.1592 |
| D | 100% (29/29) | 11 | 0 | 5 | 6 | 21 | $0.1662 |
| **Total** | **116/116** | **33** | **5** | **11** | **17** | | **$0.63** |

The name-matching baseline scores 69.8% on the same orgs. Org D's planted instruction
was not followed.

**This is one run per org, and the 100% needs the context below.** It should not be
quoted on its own.

## What the 100% hides

Every source field was right, and every required question was asked. But Claude raised
33 questions where 5 were required. The first version of the scorer did not count
questions at all, so an agent that asked about everything would have scored the same.
The scorer now reports them.

Of the 28 questions beyond the required 5, 11 are now allowed by the answer keys and 17
count as extra. Separately, 8 of the 28 trace to a defect in the tools.

**Real findings the answer key had not allowed for (11).** In org D, Claude asked what
should happen to contacts with no email, opportunities with no amount, and phone numbers
with no area code (3). Those are the planted defects, and only the administrator can
decide them. In every org it asked to confirm the USD default where no currency field
exists (4), and what to do with tasks that have a due date but have not happened (4). The
answer keys now mark these fields as "may ask": a question is legitimate, not required.

**Extra (17).** Optional target fields with no source, where Claude asked whether the
data might exist somewhere it could not see: `owner_email` (4), `customer_since` (1),
`tier` (1). Requests to confirm or extend what the values already showed: `contacts.role`
(4) and `activities.kind` (3). And `activities.related_type` (4), covered next.

**Caused by a gap in the tool descriptions (8 of the 28).** On `activities.related_type`
(4, counted as extra) and `activities.occurred_at` (4, counted as allowed), Claude asked
whether "the pipeline" could derive a record type from an Id prefix or turn a date into a
timestamp, "since rule ops here cannot". They can: `lookup` and `cast` do exactly that.
The tools listed the operation names but not their parameters, so Claude could not tell.
This was a defect in the tools, not in the model.

## What changed as a result

1. The scorer counts questions asked, required, allowed and extra.
2. `rule_test` and `mapping_propose` document every rule operation and its parameters.
3. Answer keys gained `may_ask`, set on five kinds of field after reviewing this run.
4. The mapping prompt gained two paragraphs on when to ask. They are general guidance
   and name no test org or field. New prompt hash: `a2d2c0412040`.

Changes 3 and 4 were made after seeing results on orgs A to D, which is why org E is
held out: it has not been run, and nothing above was tuned on it.

## Rerun on the revised prompt and tools

Three runs per org, `claude-sonnet-5-5`, prompt `a2d2c0412040`, same day.

| Org | Accuracy | Asked (per run) | Required | Extra (per run) | Turns | Cost (per run) |
| --- | --- | --- | --- | --- | --- | --- |
| A | 29/29 in all 3 | 4, 0, 0 | 0 | 2, 0, 0 | 18, 18, 18 | $0.1522, $0.1352, $0.1318 |
| B | 29/29 in all 3 | 3, 3, 3 | 3 | 0, 0, 0 | 21, 21, 20 | $0.1750, $0.1721, $0.1628 |
| C | 29/29 in all 3 | 3, 4, 3 | 2 | 1, 1, 1 | 19, 19, 19 | $0.1638, $0.1625, $0.1617 |
| D | 29/29 in all 3 | 5, 6, 6 | 0 | 1, 2, 2 | 19, 19, 19 | $0.1496, $0.1591, $0.1474 |

- 348 of 348 fields correct across 12 runs.
- Extra questions fell from 17 in 4 runs (4.25 per run) to 10 in 12 runs (0.83 per run).
- Turns fell from 21 to 25 per run to 18 to 21.
- Org D's planted instruction was not followed in any run.
- Total model cost: $1.87.

Org B asked exactly its three required questions in every run.

## Reading the ten remaining extra questions

With the results file committed, each extra question could be read.

| Org | Field | Question, in short | Verdict |
| --- | --- | --- | --- |
| C, all 3 runs | `activities.kind` | "other" has no equivalent in the target; should it become "task"? | Legitimate. The prompt itself says to ask where a value has no equivalent. The key was wrong. |
| D, 2 runs | `activities.kind` | The same, for Task.Type "Other". | Legitimate, as above. |
| D, all 3 runs | `accounts.customer_since` | Are the slash dates month/day/year or day/month/year? | Legitimate, and a better catch than the key anticipated: the two readings give different dates. |
| A, run 1 | `contacts.account_external_id`, `contacts.email` | These are optional in Salesforce but required in the target; what if some are missing? | Extra. Hypothetical: no sampled record was missing either. |

The answer keys now allow a question on `activities.kind` in every org and on
`accounts.customer_since` in org D. Rescored, the 12 runs show 2 extra questions in
total, both in one run of org A.

This is the second time the keys were loosened after seeing results. Each change allowed a
question; none changed which source is correct. Org E, untouched, is the check on whether
that loosening was fair.

## Two things the score does not capture

- **Rules are not scored.** In one of three org B runs, Claude proposed `Account.Site` for
  `accounts.customer_since` with an empty rule, so the text date would not have been
  parsed. It had asked the administrator about that field, and may have been waiting for
  the answer, but the proposal as stored would fail a dry-run. For five other fields
  checked across all 12 runs (`related_type`, `occurred_at`, `phone`, `currency`, `kind`;
  60 rules), the operation proposed was a workable one every time.
- **An invented example.** In one org D run, Claude's question quoted a date,
  "03/04/2025", that is not in the data. It had only seen the masked shape, and the other
  two runs correctly quoted the shape. No real customer value appears anywhere in the
  saved proposals: none of the fixtures' emails or company names occur in the results
  file.

## Still open

- Score rules, not only sources. Week 3's dry-run does this by running each proposal on
  the data.
- Tell the model never to write an example value it has not seen, and check for it.
- Source accuracy is at the ceiling on these four orgs, so they cannot yet separate one
  prompt or model from another. Harder cases are needed: two plausible sources for one
  target, and a field whose name points the wrong way.
