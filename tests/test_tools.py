import json

import pytest

from firstsync import tools
from firstsync.connections import UnknownConnection, get_client, orgs_dir
from firstsync.salesforce import FixtureSalesforceClient, ObjectNotAccessible


def _raw(org):
    return json.loads((orgs_dir() / org / "fixture.json").read_text())


def test_check_access_lists_the_custom_object(org_b):
    result = tools.sf_check_access(org_b)
    names = {o["name"]: o for o in result["readable"]}
    assert set(names) == {"Account", "Contact", "Deal__c", "Task"}
    assert names["Deal__c"]["custom"] is True
    assert result["missing"] == []


def test_check_access_names_the_fix_for_a_denied_object():
    fixture = _raw("org_a") | {"denied_objects": ["Opportunity"]}
    result = tools.sf_check_access(FixtureSalesforceClient(fixture))
    assert [m["object"] for m in result["missing"]] == ["Opportunity"]
    assert "permission set" in result["missing"][0]["fix"]
    assert "Opportunity" not in [o["name"] for o in result["readable"]]


def test_denied_field_disappears_from_describe_and_samples():
    fixture = _raw("org_a") | {"denied_fields": {"Contact": ["Email"]}}
    client = FixtureSalesforceClient(fixture)
    described = [f["name"] for f in tools.sf_describe_object(client, "Contact")["fields"]]
    assert "Email" not in described
    assert all("Email" not in r for r in tools.sf_sample_records(client, "Contact")["records"])


def test_describe_returns_picklist_values_and_required_flags(org_b):
    fields = {f["name"]: f for f in tools.sf_describe_object(org_b, "Deal__c")["fields"]}
    assert "Legal Hold" in fields["Deal_Phase__c"]["picklist_values"]
    assert fields["Name"]["required"] is True
    assert fields["Amt__c"]["required"] is False
    assert fields["Account__c"]["reference_to"] == ["Account"]


def test_counts_default_to_every_readable_object(org_a):
    assert tools.sf_count_records(org_a)["counts"] == {
        "Account": 40,
        "Contact": 120,
        "Opportunity": 80,
        "Task": 150,
    }


def test_count_reports_an_unreadable_object_without_failing(org_a):
    counts = tools.sf_count_records(org_a, ["Account", "Lead"])["counts"]
    assert counts["Account"] == 40
    assert "error" in counts["Lead"]


def test_samples_are_capped_and_masked(org_b):
    raw_emails = {r["Email"] for r in _raw("org_b")["objects"]["Contact"]["records"]}
    result = tools.sf_sample_records(org_b, "Contact", limit=500)
    assert result["returned"] == 50
    for record in result["records"]:
        assert record["Email"] not in raw_emails
        assert "@" in record["Email"]  # the shape survives
    assert result["masking"]["Department"] == "categorical"


def test_repurposed_date_field_keeps_its_shape(org_b):
    record = tools.sf_sample_records(org_b, "Account", limit=1)["records"][0]
    assert record["Site"] == "99/99/9999"
    assert record["Acct_Tier__c"] in {"T1", "T2", "T3"}


def test_masking_does_not_depend_on_how_many_records_are_requested(org_b):
    one = tools.sf_sample_records(org_b, "Account", limit=1)
    fifty = tools.sf_sample_records(org_b, "Account", limit=50)
    assert one["returned"] == 1
    assert one["masking"] == fifty["masking"]
    assert one["masking"]["Field_7__c"] == "categorical"


@pytest.mark.parametrize("bad", ["Account; DROP", "Account FROM Contact", "", "1Account", "a" * 90])
def test_object_names_that_are_not_api_names_are_rejected(org_a, bad):
    with pytest.raises(ValueError):
        tools.sf_describe_object(org_a, bad)
    with pytest.raises(ValueError):
        tools.sf_sample_records(org_a, bad)


def test_unknown_object_is_not_accessible(org_a):
    with pytest.raises(ObjectNotAccessible):
        tools.sf_describe_object(org_a, "Lead")


def test_target_schema_lists_required_fields():
    result = tools.target_get_schema()
    assert set(result["schema"]["tables"]) == {"accounts", "contacts", "deals", "activities"}
    assert "deals.stage" in result["required"]
    assert "accounts.tier" not in result["required"]


@pytest.mark.parametrize("handle", ["../etc", "ORG_A", "org a", "nope"])
def test_bad_connection_handles_are_refused(handle):
    with pytest.raises(UnknownConnection):
        get_client(handle)
