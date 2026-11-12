"""Deterministic generators for the synthetic test orgs.

Everything here is invented. Company names, people and emails are built from word lists,
and every email uses the reserved .example domain. The same seed always produces the same
org, so the committed fixtures can be regenerated and checked.

Org A: a clean baseline. Standard objects and fields, nothing planted.
Org B: renamed and custom. Unhelpful custom field names, standard fields used for
       something else, and a custom object standing in for opportunities.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

FIRST = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Harper", "Jordan",
         "Kendall", "Logan", "Morgan", "Parker", "Quinn", "Reese", "Sawyer", "Taylor"]  # fmt: skip
LAST = ["Abbott", "Barlow", "Carver", "Dalton", "Ellery", "Farrow", "Garland", "Hollis",
        "Ingram", "Jarvis", "Keaton", "Landry", "Mercer", "Norwood", "Prescott",
        "Ridley"]  # fmt: skip
ADJECTIVE = ["Northern", "Silver", "Bright", "Cedar", "Summit", "Harbor", "Granite",
             "Prairie", "Copper", "Lakeside"]  # fmt: skip
NOUN = ["Logistics", "Foods", "Analytics", "Health", "Robotics", "Freight", "Energy",
        "Textiles", "Media", "Supply"]  # fmt: skip
SUFFIX = ["Inc", "LLC", "Group", "Co"]
INDUSTRY = ["Manufacturing", "Healthcare", "Retail", "Energy", "Financial Services", "Technology"]
TITLE = ["VP Operations", "Director of IT", "Controller", "Procurement Lead", "CTO", "Analyst"]
TASK_SUBJECT = ["Intro call", "Pricing follow-up", "Security review", "Contract redlines",
                "Quarterly check-in", "Renewal discussion"]  # fmt: skip
TASK_TYPE = ["Call", "Email", "Meeting", "Other"]
DEAL_KIND = ["Expansion", "New Business", "Renewal"]

STANDARD_STAGES = ["Prospecting", "Qualification", "Proposal/Price Quote",
                   "Negotiation/Review", "Closed Won", "Closed Lost"]  # fmt: skip
CUSTOM_PHASES = ["Prospect", "Qualified", "Proposal Sent", "Negotiating", "Won", "Lost",
                 "Legal Hold"]  # fmt: skip
TIERS = ["T1", "T2", "T3"]
BUYING_ROLES = ["Decision Maker", "Champion", "Billing", "Technical"]

BASE_DATE = date(2026, 1, 1)
N_ACCOUNTS, N_CONTACTS, N_DEALS, N_TASKS = 40, 120, 80, 150


def _id(prefix: str, n: int) -> str:
    return f"{prefix}{n:012d}AAA"


def _field(
    name: str,
    label: str,
    type_: str,
    *,
    nillable: bool = True,
    custom: bool = False,
    picklist: list[str] | None = None,
    reference_to: list[str] | None = None,
    length: int | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "type": type_,
        "nillable": nillable,
        "custom": custom,
        "defaultedOnCreate": False,
        "picklistValues": [{"value": v, "active": True} for v in picklist or []],
        "referenceTo": reference_to or [],
        "length": length,
    }


def _obj(
    name: str,
    label: str,
    fields: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    describe = {"name": name, "label": label, "custom": name.endswith("__c"), "fields": fields}
    return {"describe": describe, "records": records}


def _company(rng: random.Random, used: set[str]) -> str:
    while True:
        name = f"{rng.choice(ADJECTIVE)} {rng.choice(NOUN)} {rng.choice(SUFFIX)}"
        if name not in used:
            used.add(name)
            return name


def _slug(company: str) -> str:
    return "-".join(company.lower().split()[:2])


def _day(rng: random.Random, low: int, high: int) -> date:
    return BASE_DATE + timedelta(days=rng.randint(low, high))


def _accounts(rng: random.Random) -> list[dict[str, Any]]:
    used: set[str] = set()
    accounts = []
    for n in range(1, N_ACCOUNTS + 1):
        company = _company(rng, used)
        accounts.append(
            {
                "Id": _id("001", n),
                "Name": company,
                "Industry": rng.choice(INDUSTRY),
                "Website": f"https://www.{_slug(company)}.example",
                "_tier": rng.choice(TIERS),
                "_since": _day(rng, -1800, -30),
            }
        )
    return accounts


def _contacts(rng: random.Random, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contacts = []
    for n in range(1, N_CONTACTS + 1):
        account = accounts[(n - 1) % len(accounts)]
        first, last = rng.choice(FIRST), rng.choice(LAST)
        contacts.append(
            {
                "Id": _id("003", n),
                "AccountId": account["Id"],
                "FirstName": first,
                "LastName": last,
                "Email": f"{first}.{last}{n}@{_slug(account['Name'])}.example".lower(),
                "Phone": f"(512) 555-{rng.randint(100, 199):04d}",
                "Title": rng.choice(TITLE),
                "_role": rng.choice(BUYING_ROLES),
            }
        )
    return contacts


def _deals(rng: random.Random, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deals = []
    for n in range(1, N_DEALS + 1):
        account = rng.choice(accounts)
        deals.append(
            {
                "_n": n,
                "_account": account,
                "Name": f"{account['Name']} - {rng.choice(DEAL_KIND)}",
                "Amount": float(rng.randrange(5000, 250000, 500)),
                "_stage_index": rng.randrange(6),
                "_legal_hold": rng.random() < 0.15,
                "CloseDate": _day(rng, -120, 240).isoformat(),
                "_owner": f"{rng.choice(FIRST)}.{rng.choice(LAST)}@seller.example".lower(),
            }
        )
    return deals


def _tasks(rng: random.Random, related_ids: list[str]) -> list[dict[str, Any]]:
    tasks = []
    for n in range(1, N_TASKS + 1):
        subject = rng.choice(TASK_SUBJECT)
        tasks.append(
            {
                "Id": _id("00T", n),
                "WhatId": rng.choice(related_ids),
                "Subject": subject,
                "ActivityDate": _day(rng, -200, 0).isoformat(),
                "Status": rng.choice(["Completed", "Not Started"]),
                "Type": rng.choice(TASK_TYPE),
                "Description": f"{subject} with the customer team. Next steps agreed.",
            }
        )
    return tasks


TASK_FIELDS = [
    _field("Id", "Activity ID", "id", nillable=False),
    _field("WhatId", "Related To ID", "reference", reference_to=["Account", "Opportunity"]),
    _field("Subject", "Subject", "string", length=255),
    _field("ActivityDate", "Due Date Only", "date"),
    _field("Status", "Status", "picklist", nillable=False, picklist=["Completed", "Not Started"]),
    _field("Type", "Type", "picklist", picklist=TASK_TYPE),
    _field("Description", "Comments", "textarea", length=32000),
]


def _strip(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def build_org_a(seed: int = 101) -> dict[str, Any]:
    rng = random.Random(seed)
    accounts = _accounts(rng)
    contacts = _contacts(rng, accounts)
    deals = _deals(rng, accounts)
    opportunities = [
        {
            "Id": _id("006", d["_n"]),
            "AccountId": d["_account"]["Id"],
            "Name": d["Name"],
            "Amount": d["Amount"],
            "StageName": STANDARD_STAGES[d["_stage_index"]],
            "CloseDate": d["CloseDate"],
        }
        for d in deals
    ]
    related = [a["Id"] for a in accounts] + [o["Id"] for o in opportunities]
    return {
        "org": "org_a",
        "theme": "Clean baseline",
        "objects": {
            "Account": _obj(
                "Account",
                "Account",
                [
                    _field("Id", "Account ID", "id", nillable=False),
                    _field("Name", "Account Name", "string", nillable=False, length=255),
                    _field("Industry", "Industry", "picklist", picklist=INDUSTRY),
                    _field("Website", "Website", "url", length=255),
                ],
                [_strip(a) for a in accounts],
            ),
            "Contact": _obj(
                "Contact",
                "Contact",
                [
                    _field("Id", "Contact ID", "id", nillable=False),
                    _field("AccountId", "Account ID", "reference", reference_to=["Account"]),
                    _field("FirstName", "First Name", "string", length=40),
                    _field("LastName", "Last Name", "string", nillable=False, length=80),
                    _field("Email", "Email", "email", length=80),
                    _field("Phone", "Business Phone", "phone", length=40),
                    _field("Title", "Title", "string", length=128),
                ],
                [_strip(c) for c in contacts],
            ),
            "Opportunity": _obj(
                "Opportunity",
                "Opportunity",
                [
                    _field("Id", "Opportunity ID", "id", nillable=False),
                    _field("AccountId", "Account ID", "reference", reference_to=["Account"]),
                    _field("Name", "Name", "string", nillable=False, length=120),
                    _field("Amount", "Amount", "currency"),
                    _field(
                        "StageName", "Stage", "picklist", nillable=False, picklist=STANDARD_STAGES
                    ),
                    _field("CloseDate", "Close Date", "date", nillable=False),
                ],
                opportunities,
            ),
            "Task": _obj("Task", "Task", TASK_FIELDS, _tasks(rng, related)),
        },
    }


def build_org_b(seed: int = 202) -> dict[str, Any]:
    rng = random.Random(seed)
    accounts = _accounts(rng)
    contacts = _contacts(rng, accounts)
    deals = _deals(rng, accounts)
    account_records = [
        {
            "Id": a["Id"],
            "Name": a["Name"],
            "Field_7__c": a["Industry"],
            "Acct_Tier__c": a["_tier"],
            "Site": a["_since"].strftime("%m/%d/%Y"),
            "Website": a["Website"],
        }
        for a in accounts
    ]
    contact_records = [
        {
            "Id": c["Id"],
            "AccountId": c["AccountId"],
            "FirstName": c["FirstName"],
            "LastName": c["LastName"],
            "Email": c["Email"],
            "Phone": c["Phone"],
            "Department": c["_role"],
        }
        for c in contacts
    ]
    deal_records = [
        {
            "Id": _id("a00", d["_n"]),
            "Account__c": d["_account"]["Id"],
            "Name": d["Name"],
            "Amt__c": d["Amount"],
            "Deal_Phase__c": "Legal Hold" if d["_legal_hold"] else CUSTOM_PHASES[d["_stage_index"]],
            "Close_Dt__c": d["CloseDate"],
            "Owner_Email__c": d["_owner"],
        }
        for d in deals
    ]
    related = [a["Id"] for a in accounts] + [d["Id"] for d in deal_records]
    task_fields = [dict(f) for f in TASK_FIELDS]
    task_fields[1] = _field(
        "WhatId", "Related To ID", "reference", reference_to=["Account", "Deal__c"]
    )
    return {
        "org": "org_b",
        "theme": "Renamed and custom",
        "objects": {
            "Account": _obj(
                "Account",
                "Account",
                [
                    _field("Id", "Account ID", "id", nillable=False),
                    _field("Name", "Account Name", "string", nillable=False, length=255),
                    _field("Field_7__c", "Field 7", "string", custom=True, length=80),
                    _field("Acct_Tier__c", "Acct Tier", "picklist", custom=True, picklist=TIERS),
                    _field("Site", "Account Site", "string", length=80),
                    _field("Website", "Website", "url", length=255),
                ],
                account_records,
            ),
            "Contact": _obj(
                "Contact",
                "Contact",
                [
                    _field("Id", "Contact ID", "id", nillable=False),
                    _field("AccountId", "Account ID", "reference", reference_to=["Account"]),
                    _field("FirstName", "First Name", "string", length=40),
                    _field("LastName", "Last Name", "string", nillable=False, length=80),
                    _field("Email", "Email", "email", length=80),
                    _field("Phone", "Business Phone", "phone", length=40),
                    _field("Department", "Department", "string", length=80),
                ],
                contact_records,
            ),
            "Deal__c": _obj(
                "Deal__c",
                "Deal",
                [
                    _field("Id", "Record ID", "id", nillable=False),
                    _field(
                        "Account__c", "Account", "reference", custom=True, reference_to=["Account"]
                    ),
                    _field("Name", "Deal Name", "string", nillable=False, length=80),
                    _field("Amt__c", "Amt", "currency", custom=True),
                    _field(
                        "Deal_Phase__c", "Deal Phase", "picklist", custom=True,
                        picklist=CUSTOM_PHASES,
                    ),  # fmt: skip
                    _field("Close_Dt__c", "Close Dt", "date", custom=True),
                    _field("Owner_Email__c", "Owner Email", "email", custom=True, length=80),
                ],
                deal_records,
            ),
            "Task": _obj("Task", "Task", task_fields, _tasks(rng, related)),
        },
    }


BUILDERS = {"org_a": build_org_a, "org_b": build_org_b}
