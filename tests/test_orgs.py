import json

import httpx
import pytest

from firstsync.connections import orgs_dir
from firstsync.orgs.answer_keys import ANSWER_KEYS
from firstsync.orgs.generate import BUILDERS
from firstsync.orgs.load import LoadError, load_fixture
from firstsync.target import TARGET_SCHEMA


@pytest.mark.parametrize("org", sorted(BUILDERS))
def test_committed_fixture_matches_the_generator(org):
    committed = json.loads((orgs_dir() / org / "fixture.json").read_text())
    assert committed == json.loads(json.dumps(BUILDERS[org]()))


@pytest.mark.parametrize("org", sorted(BUILDERS))
def test_answer_key_covers_every_target_field_exactly_once(org):
    targets = [m["target"] for m in ANSWER_KEYS[org]["mappings"]]
    expected = [
        f"{table}.{field['name']}"
        for table, spec in TARGET_SCHEMA["tables"].items()
        for field in spec["fields"]
    ]
    assert sorted(targets) == sorted(expected)


@pytest.mark.parametrize("org", sorted(BUILDERS))
def test_answer_key_sources_exist_in_the_org(org):
    objects = BUILDERS[org]()["objects"]
    for mapping in ANSWER_KEYS[org]["mappings"]:
        if mapping["source"] is None:
            continue
        obj, field = mapping["source"].split(".")
        assert field in {f["name"] for f in objects[obj]["describe"]["fields"]}, mapping


@pytest.mark.parametrize("org", sorted(BUILDERS))
def test_every_reference_points_at_a_record_in_the_org(org):
    objects = BUILDERS[org]()["objects"]
    ids = {r["Id"] for obj in objects.values() for r in obj["records"]}
    for obj in objects.values():
        refs = [f["name"] for f in obj["describe"]["fields"] if f["type"] == "reference"]
        for record in obj["records"]:
            for ref in refs:
                assert record[ref] in ids


def test_only_synthetic_emails_are_generated():
    for build in BUILDERS.values():
        for obj in build()["objects"].values():
            for record in obj["records"]:
                for value in record.values():
                    if isinstance(value, str) and "@" in value:
                        assert value.endswith(".example")


def test_org_b_plants_a_stage_with_no_target_match():
    phases = {r["Deal_Phase__c"] for r in BUILDERS["org_b"]()["objects"]["Deal__c"]["records"]}
    assert "Legal Hold" in phases


def _fake_salesforce(calls):
    counter = iter(range(1, 10_000))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/composite/sobjects")
        body = json.loads(request.content)
        calls.append(body)
        results = [{"id": f"REAL{next(counter):014d}", "success": True} for _ in body["records"]]
        return httpx.Response(200, json=results)

    return httpx.MockTransport(handler)


def test_loader_inserts_parents_first_and_rewrites_references():
    calls = []
    fixture = BUILDERS["org_b"]()
    created = load_fixture(fixture, "https://x.example", "token", transport=_fake_salesforce(calls))
    assert created == {"Account": 40, "Contact": 120, "Deal__c": 80, "Task": 150}
    order = [c["records"][0]["attributes"]["type"] for c in calls]
    assert order == ["Account", "Contact", "Deal__c", "Task"]
    for call in calls:
        assert len(call["records"]) <= 200
        for record in call["records"]:
            assert "Id" not in record
    contact = calls[1]["records"][0]
    assert contact["AccountId"].startswith("REAL")


def test_loader_stops_on_a_failed_record():
    def handler(request):
        body = json.loads(request.content)
        failed = {"success": False, "errors": [{"message": "bad"}]}
        return httpx.Response(200, json=[failed for _ in body["records"]])

    with pytest.raises(LoadError):
        load_fixture(
            BUILDERS["org_a"](), "https://x.example", "t", transport=httpx.MockTransport(handler)
        )
