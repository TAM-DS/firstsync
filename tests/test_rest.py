import httpx
import pytest

from firstsync import tools
from firstsync.salesforce import ObjectNotAccessible, RestSalesforceClient, SalesforceError

DESCRIBE = {
    "name": "Account",
    "label": "Account",
    "custom": False,
    "fields": [
        {"name": "Id", "type": "id", "nillable": False, "defaultedOnCreate": True},
        {"name": "Name", "type": "string", "nillable": False, "defaultedOnCreate": False},
        {"name": "BillingAddress", "type": "address", "nillable": True},
        {"name": "Phone", "type": "phone", "nillable": True},
    ],
}


def _client(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer token"
        path = request.url.path.removeprefix("/services/data/v62.0")
        if path == "/sobjects":
            return httpx.Response(
                200,
                json={
                    "sobjects": [
                        {"name": "Account", "queryable": True, "custom": False},
                        {"name": "Contact", "queryable": True, "custom": False},
                        {"name": "Task", "queryable": True, "custom": False},
                        {"name": "Deal__c", "queryable": True, "custom": True},
                        {"name": "Deal__Share", "queryable": True, "custom": True},
                        {"name": "Lead", "queryable": True, "custom": False},
                    ]
                },
            )
        if path == "/sobjects/Account/describe":
            return httpx.Response(200, json=DESCRIBE)
        if path == "/sobjects/Opportunity/describe":
            return httpx.Response(404, json=[{"errorCode": "NOT_FOUND"}])
        if path == "/query":
            soql = request.url.params["q"]
            if soql.startswith("SELECT COUNT()"):
                return httpx.Response(200, json={"totalSize": 7, "records": []})
            record = {"attributes": {"type": "Account"}, "Id": "001", "Name": "Acme Inc"}
            return httpx.Response(200, json={"totalSize": 1, "records": [record]})
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    return RestSalesforceClient("https://x.example/", "token", transport=transport)


def test_accessible_objects_flags_missing_standard_objects_and_finds_custom_ones():
    objects = {o["name"]: o for o in _client([]).accessible_objects()}
    assert objects["Opportunity"]["readable"] is False
    assert objects["Deal__c"] == {
        "name": "Deal__c",
        "readable": True,
        "custom": True,
        "reason": None,
    }
    assert "Lead" not in objects  # out of scope for version 1
    assert "Deal__Share" not in objects


def test_count_uses_a_count_query():
    seen = []
    assert _client(seen).count("Account") == 7
    assert seen[-1].url.params["q"] == "SELECT COUNT() FROM Account"


def test_sample_skips_compound_fields_and_strips_attributes():
    seen = []
    result = tools.sf_sample_records(_client(seen), "Account", limit=5)
    assert seen[-1].url.params["q"] == "SELECT Id, Name, Phone FROM Account LIMIT 50"
    assert result["records"] == [{"Id": "001", "Name": "Xxxx Xxx"}]


def test_not_found_becomes_object_not_accessible():
    with pytest.raises(ObjectNotAccessible):
        _client([]).describe("Opportunity")


def test_injection_never_reaches_salesforce():
    seen = []
    client = _client(seen)
    with pytest.raises(ValueError):
        client.count("Account WHERE Name != ''")
    with pytest.raises(ValueError):
        client.sample("Account", ["Id", "Name FROM User"], 5)
    assert seen == []


def test_missing_environment_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("SF_INSTANCE_URL", raising=False)
    monkeypatch.delenv("SF_ACCESS_TOKEN", raising=False)
    with pytest.raises(SalesforceError, match="SF_INSTANCE_URL"):
        RestSalesforceClient.from_env()
