# Week 1 exit test: Claude's report on org B

This is the unedited output of `python scripts/describe_org.py org_b`, run on
12 November 2026 against the synthetic org B fixture.

| | |
| --- | --- |
| Tools available to Claude | The five read tools from the FirstSync MCP server, and nothing else |
| Turns | 12 |
| Time | 33.7 seconds |
| Model cost | $0.0791 |
| Model | The Claude Agent SDK default (`FIRSTSYNC_MODEL` was not set; the run did not record the model name) |

**Result against the answer key** (`orgs/org_b/answer_key.json`): all six planted problems
were found.

| Planted in org B | Claude's report |
| --- | --- |
| `Field_7__c` holds the industry | Found, citing the six values |
| `Account.Site` holds a date as text | Found from the masked shape; asked which date and which format |
| `Acct_Tier__c` uses T1/T2/T3 | Found; asked which tier is which |
| `Contact.Department` holds the buying role | Found and matched to the target's role values |
| `Deal__c` replaces Opportunity | Found |
| `Legal Hold` has no target stage | Found, counted 11 of 50 sampled |

It also raised three things that were not planted but are real in the generated data:
tasks marked "Not Started", task dates with no time of day, and open deals with close
dates in the past.

This is one run on one org. It is not an accuracy measurement; that comes with the
week 2 evaluation across all five orgs.

---

# Salesforce org `org_b`: what's in it and how it fits FirstSync

I only read data. Nothing was changed in your Salesforce org or in FirstSync.

## 1. What I can and cannot read

I can read all four objects in scope: **Account, Contact, Deal (a custom object) and Task**. Nothing in scope was blocked.

Salesforce hides fields this user isn't allowed to see without saying so. Some standard fields I'd normally expect are missing:
- **Account:** Owner and Industry
- **Contact:** Title
- **Task:** Who (the person the task is about)

Either your org doesn't use them, or this user isn't allowed to see them. I can't tell which.

## 2. What each object holds

| Object | Records | Records I sampled | What it holds | Where it goes in FirstSync |
|---|---|---|---|---|
| Account | 40 | all 40 | Customer companies: name, website and 3 other fields (see section 3) | accounts |
| Contact | 120 | 50 | People at those companies: name, email, phone, company link, and a "Department" field | contacts |
| Deal (custom) | 80 | 50 | Sales deals: name, company, amount, phase, close date, owner email | deals |
| Task | 150 | 50 | Calls, emails and meetings linked to a company or a deal: subject, date, type, status, comments | activities |

Every sampled contact and deal is linked to a company, and every sampled task is linked to a company or a deal.

## 3. Unusual things

**Account**
- **"Field 7"** is a custom field with a meaningless name. In all 40 records it holds an industry: Healthcare, Energy, Technology, Retail, Financial Services or Manufacturing. It looks like it belongs in FirstSync's **industry** field.
- **"Account Site"** is a standard Salesforce field normally used for an office location. Here, all 40 records hold a date-shaped value (99/99/9999 once masked), so it has been reused for some date. It might be "customer since", but that's a guess. I also can't tell whether the dates are month/day or day/month.
- **"Acct Tier"** has three values: T1, T2 and T3. FirstSync's tiers are free, standard and enterprise, and I can't tell which matches which.
- **No owner field.** FirstSync's account owner email would stay empty.

**Contact**
- **"Department"** is a standard field being used for something else. Its values are Billing, Decision Maker, Champion and Technical. Those match FirstSync's **role** values (billing, decision_maker, champion, technical), not real departments.
- **Phone numbers** are written like (999) 999-9999, which looks like US format. FirstSync wants international format (+1…).
- **Email isn't mandatory** in Salesforce but is in FirstSync. All 50 sampled contacts have one; I haven't checked the other 70.

**Deal**
- **This is a custom object**, used instead of Salesforce's standard Opportunity.
- **"Legal Hold"** is a deal phase with no equivalent in FirstSync. It's common: 11 of the 50 sampled deals are in it. The other phases match cleanly: Prospect→lead, Qualified→qualified, Proposal Sent→proposal, Negotiating→negotiation, Won→closed_won, Lost→closed_lost.
- **No currency field.** FirstSync requires one; its default is USD.
- **Old close dates on open deals.** Some deals still in Proposal Sent, Legal Hold or Prospect have close dates in 2025. This is a data quality note, not a blocker.

**Task**
- **No time of day.** FirstSync needs the date and time each activity happened. Salesforce only has a date, and its label is "Due Date Only".
- **Not all tasks have happened.** Many are "Not Started". FirstSync activities are meant to be things that already happened, and these dates are all in 2025, so they are planned items that are now overdue.
- **"Other" has no match.** Task types are Call, Email, Meeting and Other. FirstSync's kinds are call, email, meeting and task, so Other has no obvious place.
- **What the comments contain is unknown.** They were masked down to their length (53–61 characters), so I can't describe their content.

## 4. Questions before mapping

1. Does **Field 7** hold the company's industry? Should it go into FirstSync's industry field?
2. What date is stored in **Account Site**? Is it "customer since"? Are the dates month/day/year or day/month/year?
3. Which **tier** is T1, which is T2, and which is T3 (free, standard, enterprise)?
4. Can you confirm **Department** holds the contact's buying role? Are all phone numbers US numbers, so +1 can be added?
5. Where should **"Legal Hold"** deals go: negotiation, proposal, or somewhere else?
6. Are all deal amounts in **US dollars**? If not, where is the currency recorded?
7. For **tasks still "Not Started"**: should they be brought over, left out, or brought over as kind "task"?
8. What time should go with task dates, for example midnight UTC? And which time zone are the dates in?
9. What should task type **"Other"** become in FirstSync?
10. Are an account **owner** field and a standard **Industry** field in use but hidden from this user? If so, could you give the connection permission to read them?
