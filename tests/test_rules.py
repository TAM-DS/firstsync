import pytest

from firstsync.mapping import target_fields
from firstsync.rules import (
    RuleFailure,
    UnmappedValue,
    apply_rule,
    asks_admin,
    check_target_value,
    validate_rule,
)

STAGES = {"Prospect": "lead", "Won": "closed_won"}


def run(rule, value, record=None):
    assert validate_rule(rule) == []
    return apply_rule(rule, value, record)


def test_copy_trim_and_case():
    assert run([{"op": "copy"}], "x") == "x"
    assert run([{"op": "trim"}, {"op": "case", "to": "lower"}], "  Energy ") == "energy"


@pytest.mark.parametrize(
    ("to", "value", "expected"),
    [
        ("integer", "1,200", 1200),
        ("number", "12.5", 12.5),
        ("boolean", "Yes", True),
        ("string", 7, "7"),
        ("date", "2026-03-14T10:00:00Z", "2026-03-14"),
        ("timestamp", "2026-03-14", "2026-03-14T00:00:00Z"),
    ],
)
def test_cast(to, value, expected):
    assert run([{"op": "cast", "to": to}], value) == expected


def test_cast_failure_does_not_echo_the_value():
    with pytest.raises(RuleFailure) as failure:
        run([{"op": "cast", "to": "number"}], "secret-value")
    assert "secret-value" not in str(failure.value)


def test_parse_date_tries_each_format():
    rule = [{"op": "parse_date", "formats": ["%Y-%m-%d", "%m/%d/%Y", "%d %b %Y"]}]
    assert run(rule, "03/14/2021") == "2021-03-14"
    assert run(rule, "14 Mar 2021") == "2021-03-14"
    assert run(rule, "2021-03-14") == "2021-03-14"
    with pytest.raises(RuleFailure):
        run(rule, "March 2021")


def test_map_values_modes():
    assert run([{"op": "map_values", "table": STAGES}], "Won") == "closed_won"
    with pytest.raises(RuleFailure):
        run([{"op": "map_values", "table": STAGES}], "Legal Hold")
    with pytest.raises(UnmappedValue):
        run([{"op": "map_values", "table": STAGES, "unmapped": "ask_admin"}], "Legal Hold")
    assert run([{"op": "map_values", "table": STAGES, "unmapped": "null"}], "Legal Hold") is None
    assert run([{"op": "map_values", "table": STAGES, "unmapped": "keep"}], "Other") == "Other"
    insensitive = [{"op": "map_values", "table": {"call": "call"}, "case_insensitive": True}]
    assert run(insensitive, "CALL") == "call"


def test_lookup_maps_a_record_id_prefix():
    rule = [{"op": "lookup", "prefix_length": 3, "table": {"001": "account", "006": "deal"}}]
    assert run(rule, "006000000000012AAA") == "deal"


def test_split_concat_and_default():
    assert run([{"op": "split", "separator": ",", "index": 1}], "a, b") == "b"
    with pytest.raises(RuleFailure):
        run([{"op": "split", "separator": ",", "index": 3}], "a,b")
    record = {"FirstName": "Dana", "LastName": "Reyes"}
    full_name = [{"op": "concat", "fields": ["FirstName", "LastName"]}]
    assert run(full_name, None, record) == "Dana Reyes"
    assert run([{"op": "default", "value": "USD"}], None) == "USD"
    assert run([{"op": "default", "value": "USD"}], "EUR") == "EUR"


@pytest.mark.parametrize(
    "value", ["(512) 555-0142", "512-555-0142", "512.555.0142", "+1 512 555 0142", "15125550142"]
)
def test_normalize_phone_accepts_the_common_formats(value):
    assert run([{"op": "normalize_phone"}], value) == "+15125550142"


def test_normalize_phone_rejects_a_number_without_an_area_code():
    with pytest.raises(RuleFailure):
        run([{"op": "normalize_phone"}], "555-0142")


def test_empty_values_pass_through_as_null():
    assert run([{"op": "trim"}, {"op": "cast", "to": "number"}], "  ") is None
    assert run([{"op": "normalize_phone"}], None) is None


@pytest.mark.parametrize(
    "rule",
    [
        "copy",
        [{"op": "eval", "code": "1"}],
        [{"op": "python"}],
        [{"op": "copy", "extra": 1}],
        [{"op": "case"}],
        [{"op": "case", "to": "snake"}],
        [{"op": "cast", "to": "object"}],
        [{"op": "parse_date", "formats": ["%Y-%m-%d; import os"]}],
        [{"op": "parse_date", "formats": []}],
        [{"op": "map_values", "table": {}}],
        [{"op": "map_values", "table": {"a": ["x"]}}],
        [{"op": "map_values", "table": {"a": "b"}, "unmapped": "guess"}],
        [{"op": "lookup", "prefix_length": 0, "table": {"a": "b"}}],
        [{"op": "split", "separator": "", "index": 0}],
        [{"op": "concat", "fields": ["Name FROM User"]}],
        [{"op": "default", "value": {"a": 1}}],
        [{"op": "normalize_phone", "default_country_code": "+1"}],
        [{"op": "copy"}] * 9,
        [42],
    ],
)
def test_invalid_rules_are_rejected(rule):
    assert validate_rule(rule) != []


def test_asks_admin_detects_deferred_values():
    assert asks_admin([{"op": "map_values", "table": STAGES, "unmapped": "ask_admin"}])
    assert not asks_admin([{"op": "map_values", "table": STAGES}])


@pytest.mark.parametrize(
    ("target", "value", "ok"),
    [
        ("deals.stage", "closed_won", True),
        ("deals.stage", "Won", False),
        ("deals.stage", None, False),
        ("accounts.tier", None, True),
        ("deals.amount", 1200.0, True),
        ("deals.amount", "1200", False),
        ("contacts.email", "a@b.example", True),
        ("contacts.email", "not-an-email", False),
        ("accounts.customer_since", "2021-03-14", True),
        ("accounts.customer_since", "03/14/2021", False),
        ("activities.occurred_at", "2026-01-05T00:00:00Z", True),
        ("activities.occurred_at", "2026-01-05", False),
        ("contacts.phone", "+15125550142", True),
        ("contacts.phone", "(512) 555-0142", False),
    ],
)
def test_check_target_value(target, value, ok):
    assert (check_target_value(target_fields()[target], value) is None) is ok
