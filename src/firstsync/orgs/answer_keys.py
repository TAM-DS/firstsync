"""Answer keys: the correct source for every target field, per test org.

`source` is "Object.Field", or None when the org has nothing that belongs in that target
field. A None is a real answer: proposing a mapping there is a mistake the evaluation
counts. `rule` names the transformation a correct mapping needs, in plain words; the
week 2 evaluation compares against the rule format once it exists.
"""

from __future__ import annotations

from typing import Any


def _m(target: str, source: str | None, rule: str = "copy", note: str | None = None) -> dict:
    entry: dict[str, Any] = {"target": target, "source": source, "rule": rule}
    if note:
        entry["note"] = note
    return entry


_ACTIVITIES = [
    _m("activities.external_id", "Task.Id"),
    _m("activities.related_type", "Task.WhatId", "derive from the referenced object"),
    _m("activities.related_external_id", "Task.WhatId"),
    _m("activities.kind", "Task.Type", "map values; 'Other' becomes 'task'"),
    _m("activities.subject", "Task.Subject"),
    _m("activities.occurred_at", "Task.ActivityDate", "date to timestamp"),
    _m("activities.notes", "Task.Description"),
]

ORG_A = {
    "org": "org_a",
    "planted": [],
    "mappings": [
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
        _m("deals.external_id", "Opportunity.Id"),
        _m("deals.account_external_id", "Opportunity.AccountId"),
        _m("deals.name", "Opportunity.Name"),
        _m("deals.amount", "Opportunity.Amount"),
        _m("deals.currency", None, "default USD"),
        _m("deals.stage", "Opportunity.StageName", "map values"),
        _m("deals.close_date", "Opportunity.CloseDate"),
        _m("deals.owner_email", None),
        *_ACTIVITIES,
    ],
}

ORG_B = {
    "org": "org_b",
    "planted": [
        "Account.Field_7__c holds the industry under an unhelpful name.",
        "Account.Acct_Tier__c uses T1/T2/T3 for enterprise/standard/free.",
        "Account.Site, a standard field, holds the customer-since date as MM/DD/YYYY text.",
        "Contact.Department, a standard field, holds the buying role.",
        "Deal__c, a custom object, stands in for Opportunity.",
        "Deal__c.Deal_Phase__c has a value, 'Legal Hold', with no matching target stage.",
    ],
    "mappings": [
        _m("accounts.external_id", "Account.Id"),
        _m("accounts.name", "Account.Name"),
        _m("accounts.industry", "Account.Field_7__c"),
        _m("accounts.tier", "Account.Acct_Tier__c", "map values T1/T2/T3"),
        _m("accounts.website", "Account.Website"),
        _m("accounts.customer_since", "Account.Site", "parse date MM/DD/YYYY"),
        _m("accounts.owner_email", None),
        _m("contacts.external_id", "Contact.Id"),
        _m("contacts.account_external_id", "Contact.AccountId"),
        _m("contacts.first_name", "Contact.FirstName"),
        _m("contacts.last_name", "Contact.LastName"),
        _m("contacts.email", "Contact.Email"),
        _m("contacts.phone", "Contact.Phone", "normalize to E.164"),
        _m("contacts.role", "Contact.Department", "map values"),
        _m("deals.external_id", "Deal__c.Id"),
        _m("deals.account_external_id", "Deal__c.Account__c"),
        _m("deals.name", "Deal__c.Name"),
        _m("deals.amount", "Deal__c.Amt__c"),
        _m("deals.currency", None, "default USD"),
        _m(
            "deals.stage",
            "Deal__c.Deal_Phase__c",
            "map values",
            note="'Legal Hold' has no match; the admin must be asked.",
        ),
        _m("deals.close_date", "Deal__c.Close_Dt__c"),
        _m("deals.owner_email", "Deal__c.Owner_Email__c"),
        *_ACTIVITIES,
    ],
}

ANSWER_KEYS = {"org_a": ORG_A, "org_b": ORG_B}
