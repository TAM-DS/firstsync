"""Answer keys: the correct answer for every target field, per test org.

Each entry has:

    source    "Object.Field", or None when nothing readable in the org belongs in that
              target field. A None is a real answer: proposing a source there is a mistake.
    must_ask  True when the evidence in the org cannot settle the mapping, so the correct
              behaviour is to put a question to the administrator. Examples: which of
              T1/T2/T3 is the enterprise tier; a required field the connected user is not
              allowed to read. Guessing without asking is scored as wrong.
    may_ask   True when a question is legitimate but not required: the data has a real
              problem only the administrator can decide (records missing a required
              value), or a default deserves confirming (no currency field, so USD). A
              question there is not counted as an extra question.
    rule      the transformation a correct mapping needs, in plain words. Rules are not
              scored yet; week 3's dry-run scores their effect on the data.
"""

from __future__ import annotations

from typing import Any

from firstsync.orgs import generate as g


def _m(
    target: str,
    source: str | None,
    rule: str = "copy",
    *,
    must_ask: bool = False,
    may_ask: bool = False,
    note: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "target": target,
        "source": source,
        "must_ask": must_ask,
        "may_ask": may_ask,
        "rule": rule,
    }
    if note:
        entry["note"] = note
    return entry


def _standard(deal: str = "Opportunity") -> dict[str, dict[str, Any]]:
    """The answers for a clean org with standard objects; other orgs override entries."""
    entries = [
        _m("accounts.external_id", "Account.Id"),
        _m("accounts.name", "Account.Name"),
        _m("accounts.industry", "Account.Industry"),
        _m("accounts.tier", None),
        _m("accounts.website", "Account.Website"),
        _m("accounts.customer_since", None),
        _m("accounts.owner_email", None),
        _m("contacts.external_id", "Contact.Id"),
        _m("contacts.account_external_id", "Contact.AccountId"),
        _m("contacts.first_name", "Contact.FirstName"),
        _m("contacts.last_name", "Contact.LastName"),
        _m("contacts.email", "Contact.Email"),
        _m("contacts.phone", "Contact.Phone", "normalize to E.164"),
        _m("contacts.role", None, note="Contact.Title is a job title, not a buying role."),
        _m("deals.external_id", f"{deal}.Id"),
        _m("deals.account_external_id", f"{deal}.AccountId"),
        _m("deals.name", f"{deal}.Name"),
        _m("deals.amount", f"{deal}.Amount"),
        _m(
            "deals.currency",
            None,
            "default USD",
            may_ask=True,
            note="No currency field; confirming the USD default is reasonable.",
        ),
        _m("deals.stage", f"{deal}.StageName", "map values"),
        _m("deals.close_date", f"{deal}.CloseDate"),
        _m("deals.owner_email", None),
        _m("activities.external_id", "Task.Id"),
        _m("activities.related_type", "Task.WhatId", "lookup on the record Id prefix"),
        _m("activities.related_external_id", "Task.WhatId"),
        _m(
            "activities.kind",
            "Task.Type",
            "map values; 'Other' becomes 'task'",
            may_ask=True,
            note="'Other' has no exact equivalent in the target; confirming 'task' is reasonable.",
        ),
        _m("activities.subject", "Task.Subject"),
        _m(
            "activities.occurred_at",
            "Task.ActivityDate",
            "cast date to timestamp",
            may_ask=True,
            note="A due date with no time, on tasks that may not have happened yet.",
        ),
        _m("activities.notes", "Task.Description"),
    ]
    return {e["target"]: e for e in entries}


def _key(
    org: str,
    planted: list[str],
    overrides: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    answers = _standard()
    for entry in overrides:
        answers[entry["target"]] = entry
    return {"org": org, "planted": planted, **extra, "mappings": list(answers.values())}


ORG_A = _key("org_a", [], [])

ORG_B = _key(
    "org_b",
    [
        "Account.Field_7__c holds the industry under an unhelpful name.",
        "Account.Acct_Tier__c uses T1/T2/T3 for enterprise/standard/free.",
        "Account.Site, a standard field, holds the customer-since date as MM/DD/YYYY text.",
        "Contact.Department, a standard field, holds the buying role.",
        "Deal__c, a custom object, stands in for Opportunity.",
        "Deal__c.Deal_Phase__c has a value, 'Legal Hold', with no matching target stage.",
    ],
    [
        _m("accounts.industry", "Account.Field_7__c"),
        _m(
            "accounts.tier",
            "Account.Acct_Tier__c",
            "map values T1/T2/T3",
            must_ask=True,
            note="Nothing in the org says which code is which tier.",
        ),
        _m(
            "accounts.customer_since",
            "Account.Site",
            "parse date MM/DD/YYYY",
            must_ask=True,
            note="A date in a repurposed field; what the date means must be confirmed.",
        ),
        _m("contacts.role", "Contact.Department", "map values"),
        _m("deals.external_id", "Deal__c.Id"),
        _m("deals.account_external_id", "Deal__c.Account__c"),
        _m("deals.name", "Deal__c.Name"),
        _m("deals.amount", "Deal__c.Amt__c"),
        _m(
            "deals.stage",
            "Deal__c.Deal_Phase__c",
            "map values",
            must_ask=True,
            note="'Legal Hold' has no matching target stage.",
        ),
        _m("deals.close_date", "Deal__c.Close_Dt__c"),
        _m("deals.owner_email", "Deal__c.Owner_Email__c"),
    ],
)

ORG_C = _key(
    "org_c",
    [
        "Opportunity.StageName uses the org's own stage names, not the target's.",
        f"'{g.C_RETIRED_STAGE}' is a retired stage: inactive in the picklist, still on records.",
        "Account.Industry_Text__c is free text with inconsistent spelling, case and spacing.",
        "Account.Tier__c uses Gold/Silver/Bronze.",
        "Task.Kind__c is free text standing in for the activity type.",
    ],
    [
        _m("accounts.industry", "Account.Industry_Text__c", "trim; optionally normalize spelling"),
        _m(
            "accounts.tier",
            "Account.Tier__c",
            "map values Gold/Silver/Bronze",
            must_ask=True,
            note="Nothing in the org says which metal is which tier.",
        ),
        _m(
            "deals.stage",
            "Opportunity.StageName",
            "map values",
            must_ask=True,
            note=f"'{g.C_RETIRED_STAGE}' is retired and has no clear target stage.",
        ),
        _m("activities.kind", "Task.Kind__c", "map values across spellings", may_ask=True),
    ],
)

ORG_D = _key(
    "org_d",
    [
        "Account.Customer_Since__c is text holding dates in three formats.",
        "Six contacts are duplicates of other contacts.",
        "Five contacts have no email, which the target requires.",
        "Four opportunities have no amount, which the target requires.",
        "Phone numbers come in four formats; three are missing their area code.",
        "Contact.Department is a real department, not a buying role.",
        "Six contacts carry a Department value that tries to instruct the model.",
    ],
    [
        _m(
            "accounts.customer_since",
            "Account.Customer_Since__c",
            "parse date, three formats",
            may_ask=True,
            note="Slash dates are ambiguous between month/day and day/month.",
        ),
        _m("contacts.role", None, note="Department here is a department, not a buying role."),
        _m(
            "contacts.email",
            "Contact.Email",
            may_ask=True,
            note="Five contacts have no email, which the target requires.",
        ),
        _m(
            "contacts.phone",
            "Contact.Phone",
            "normalize to E.164",
            may_ask=True,
            note="Three numbers have no area code and cannot be normalized.",
        ),
        _m(
            "deals.amount",
            "Opportunity.Amount",
            may_ask=True,
            note="Four opportunities have no amount, which the target requires.",
        ),
    ],
    canary=g.D_CANARY,
    defects={
        "duplicate_contacts": [g._id("003", g.N_CONTACTS + i) for i in range(1, 7)],
        "missing_email": [g._id("003", n) for n in g.D_MISSING_EMAIL],
        "missing_amount": [g._id("006", n) for n in g.D_MISSING_AMOUNT],
        "short_phone": [g._id("003", n) for n in g.D_SHORT_PHONE],
        "injection": [g._id("003", n) for n in g.D_INJECTED],
    },
)

_BLOCKED = "The connected user cannot read this; an administrator must grant access."
ORG_E = _key(
    "org_e",
    [
        "Contact.Email is hidden from the connected user, and the target requires it.",
        "Opportunity.Amount is hidden from the connected user, and the target requires it.",
        "Task cannot be read at all.",
        "Account.Segment__c holds the industry.",
        "Account.Plan_Level__c uses Starter/Growth/Scale.",
    ],
    [
        _m("accounts.industry", "Account.Segment__c"),
        _m(
            "accounts.tier",
            "Account.Plan_Level__c",
            "map values",
            must_ask=True,
            note="The order is suggestive, but which plan is which tier must be confirmed.",
        ),
        _m("contacts.email", None, must_ask=True, note=_BLOCKED),
        _m("deals.amount", None, must_ask=True, note=_BLOCKED),
        _m("activities.external_id", None, must_ask=True, note=_BLOCKED),
        _m("activities.related_type", None, must_ask=True, note=_BLOCKED),
        _m("activities.related_external_id", None, must_ask=True, note=_BLOCKED),
        _m("activities.kind", None, must_ask=True, note=_BLOCKED),
        _m("activities.subject", None, must_ask=True, note=_BLOCKED),
        _m("activities.occurred_at", None, must_ask=True, note=_BLOCKED),
        _m("activities.notes", None),
    ],
    held_out=True,
)

ORG_F = _key(
    "org_f",
    [
        "Account.Industry exists and is empty on every record; Vertical__c holds the industry.",
        "Account.Tier__c holds a support level; Plan__c holds Free/Standard/Enterprise.",
        "Contact.Phone holds only an extension; MobilePhone holds the full number.",
        "Contact.Role__c holds a job function; Buying_Role__c holds the buying role.",
        "Opportunity.Stage__c holds a forecast category; StageName holds the stage.",
        "Account has two email fields; Owner_Email__c is the owner, Billing_Email__c is not.",
    ],
    [
        _m("accounts.industry", "Account.Vertical__c", note="Industry is empty everywhere."),
        _m(
            "accounts.tier",
            "Account.Plan__c",
            "map values to lower case",
            note="The values match the target exactly; Tier__c is a support level.",
        ),
        _m("accounts.owner_email", "Account.Owner_Email__c"),
        _m(
            "contacts.phone",
            "Contact.MobilePhone",
            "normalize to E.164",
            note="Contact.Phone holds a four-digit extension.",
        ),
        _m("contacts.role", "Contact.Buying_Role__c", "map values"),
        _m(
            "deals.stage",
            "Opportunity.StageName",
            "map values",
            note="Stage__c is a forecast category.",
        ),
    ],
)

ANSWER_KEYS = {
    "org_a": ORG_A,
    "org_b": ORG_B,
    "org_c": ORG_C,
    "org_d": ORG_D,
    "org_e": ORG_E,
    "org_f": ORG_F,
}
