import pytest

from firstsync import mapping, tools
from firstsync.connections import get_client
from firstsync.mapping import ProposalStore, SchemaCache, validate_mapping


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path / "state"))


def good(**changes):
    base = {
        "target": "accounts.industry",
        "source": "Account.Field_7__c",
        "confidence": "high",
        "reason": "All sampled values are industry names.",
        "evidence": ["sample:Account#1-40"],
        "rule": [{"op": "trim"}],
        "question_for_admin": None,
    }
    return base | changes


def errors(org_b, **changes):
    return validate_mapping(good(**changes), SchemaCache(org_b))


def test_a_good_mapping_is_valid(org_b):
    assert errors(org_b) == []


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"target": "accounts.nope"}, "Unknown target"),
        ({"source": "Account.Missing__c"}, "does not exist or is hidden"),
        ({"source": "Lead.Name"}, "cannot be read"),
        ({"source": "Account.Name; DROP"}, "'Object.Field'"),
        ({"confidence": "certain"}, "confidence"),
        ({"reason": ""}, "reason"),
        ({"evidence": []}, "evidence"),
        ({"rule": [{"op": "exec"}]}, "unknown operation"),
        ({"rule": [{"op": "concat", "fields": ["Nope__c"]}]}, "concat field"),
        ({"confidence": "low"}, "low-confidence"),
        ({"note_to_self": "x"}, "Unexpected key"),
    ],
)
def test_invalid_mappings_say_why(org_b, changes, fragment):
    assert any(fragment in e for e in errors(org_b, **changes))


def test_ask_admin_rule_needs_a_question(org_b):
    rule = [{"op": "map_values", "table": {"Won": "closed_won"}, "unmapped": "ask_admin"}]
    changes = {"target": "deals.stage", "source": "Deal__c.Deal_Phase__c", "rule": rule}
    assert any("ask_admin" in e for e in errors(org_b, **changes))
    assert errors(org_b, **changes, question_for_admin="Where should Legal Hold go?") == []


def test_required_target_without_a_source_needs_a_default_or_a_question(org_b):
    blank = {"target": "deals.currency", "source": None, "evidence": [], "rule": []}
    assert any("is required" in e for e in errors(org_b, **blank))
    assert errors(org_b, **blank | {"rule": [{"op": "default", "value": "USD"}]}) == []
    assert errors(org_b, **blank | {"question_for_admin": "Which currency?"}) == []


def test_optional_target_can_be_left_unmapped(org_b):
    assert errors(org_b, target="accounts.owner_email", source=None, evidence=[], rule=[]) == []


def test_hidden_field_cannot_be_proposed_as_a_source():
    org_e = get_client("org_e")
    result = validate_mapping(
        good(target="contacts.email", source="Contact.Email"), SchemaCache(org_e)
    )
    assert any("hidden" in e for e in result)


def test_propose_stores_valid_mappings_and_returns_the_rest(org_b):
    result = tools.mapping_propose(
        org_b, "org_b", [good(), good(target="accounts.name", source="Account.Nope")]
    )
    assert result["accepted"] == ["accounts.industry"]
    assert result["rejected"][0]["target"] == "accounts.name"
    stored = ProposalStore("org_b").load()
    assert list(stored) == ["accounts.industry"]
    assert "accounts.name" in result["coverage"]["required_without_proposal"]


def test_proposing_again_replaces_the_earlier_proposal(org_b):
    tools.mapping_propose(org_b, "org_b", [good()])
    tools.mapping_propose(org_b, "org_b", [good(confidence="medium")])
    stored = ProposalStore("org_b").load()
    assert len(stored) == 1
    assert stored["accounts.industry"]["confidence"] == "medium"


def test_propose_rejects_an_empty_or_oversized_batch(org_b):
    with pytest.raises(ValueError):
        tools.mapping_propose(org_b, "org_b", [])
    with pytest.raises(ValueError):
        tools.mapping_propose(org_b, "org_b", [good()] * 61)


def test_coverage_lists_open_questions():
    proposals = {"accounts.tier": good(target="accounts.tier", question_for_admin="Which?")}
    assert mapping.coverage(proposals)["open_questions"] == ["accounts.tier"]


# --- rule_test ---------------------------------------------------------------------------


def test_rule_test_reports_unmapped_values(org_b):
    table = {
        "Prospect": "lead",
        "Qualified": "qualified",
        "Proposal Sent": "proposal",
        "Negotiating": "negotiation",
        "Won": "closed_won",
        "Lost": "closed_lost",
    }
    rule = [{"op": "map_values", "table": table, "unmapped": "ask_admin"}]
    result = tools.rule_test(org_b, "Deal__c.Deal_Phase__c", rule, "deals.stage")
    assert result["tested"] == 50
    assert result["ok"] + result["failed"] == 50
    assert [u["value"] for u in result["unmapped_values"]] == ["Legal Hold"]


def test_rule_test_checks_results_against_the_target(org_b):
    result = tools.rule_test(org_b, "Contact.Phone", [{"op": "copy"}], "contacts.phone")
    assert result["ok"] == 0
    assert result["failures"][0]["reason"] == "value is not an E.164 phone number"
    fixed = tools.rule_test(org_b, "Contact.Phone", [{"op": "normalize_phone"}], "contacts.phone")
    assert fixed["failed"] == 0


def test_rule_test_never_returns_raw_personal_values(org_b):
    result = tools.rule_test(org_b, "Contact.Email", [{"op": "case", "to": "upper"}])
    for example in result["examples"]:
        assert ".example" not in str(example["input"]).lower()
        assert ".EXAMPLE" not in str(example["output"])


def test_rule_test_finds_the_dirty_values_in_org_d():
    org_d = get_client("org_d")
    phones = tools.rule_test(org_d, "Contact.Phone", [{"op": "normalize_phone"}], "contacts.phone")
    assert phones["failed"] == 2  # two of the three short numbers fall in the first 50
    one_format = [{"op": "parse_date", "formats": ["%Y-%m-%d"]}]
    dates = tools.rule_test(org_d, "Account.Customer_Since__c", one_format)
    assert dates["failed"] > 0
    three = [{"op": "parse_date", "formats": ["%Y-%m-%d", "%m/%d/%Y", "%d %b %Y"]}]
    assert tools.rule_test(org_d, "Account.Customer_Since__c", three)["failed"] == 0


def test_rule_test_rejects_bad_input(org_b):
    with pytest.raises(ValueError, match="Invalid rule"):
        tools.rule_test(org_b, "Account.Name", [{"op": "exec"}])
    with pytest.raises(ValueError, match="Object.Field"):
        tools.rule_test(org_b, "Account", [{"op": "copy"}])
    with pytest.raises(ValueError, match="hidden"):
        tools.rule_test(org_b, "Account.Nope__c", [{"op": "copy"}])
    with pytest.raises(ValueError, match="Unknown target"):
        tools.rule_test(org_b, "Account.Name", [{"op": "copy"}], "accounts.nope")
