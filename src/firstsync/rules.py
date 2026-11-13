"""The restricted transformation rule format.

A rule is a short list of named operations applied in order to one source value. Claude
proposes rules as data; this module validates them and runs them. Nothing Claude writes
is ever executed as code, and an operation that is not listed here is rejected.

Operations:
    copy             leave the value as it is
    trim             strip leading and trailing whitespace
    case             {"to": "upper" | "lower" | "title"}
    cast             {"to": "string" | "integer" | "number" | "boolean" | "date" | "timestamp"}
    parse_date       {"formats": ["%m/%d/%Y", ...], "output": "date" | "timestamp"}
    map_values       {"table": {...}, "unmapped": "ask_admin" | "error" | "null" | "keep",
                      "case_insensitive": false}
    lookup           {"prefix_length": 3, "table": {...}, "unmapped": ...}
                     maps the first N characters of the value, for example a record Id prefix
    split            {"separator": ",", "index": 0}
    concat           {"fields": ["FirstName", "LastName"], "separator": " "}
                     joins fields of the same source record
    default          {"value": ...} used when the value is empty
    normalize_phone  {"default_country_code": "1"} to E.164
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from firstsync.salesforce.base import NAME

RULE_HELP = "\n".join(
    [
        "A rule is a list of up to 8 steps, each an object with an 'op':",
        "- copy: leave the value as it is.",
        "- trim: strip surrounding whitespace.",
        '- case: {"op":"case","to":"upper"|"lower"|"title"}.',
        '- cast: {"op":"cast","to":"string"|"integer"|"number"|"boolean"|"date"|"timestamp"}.',
        "  Casting a date to timestamp gives midnight UTC, e.g. 2026-01-05T00:00:00Z.",
        '- parse_date: {"op":"parse_date","formats":["%m/%d/%Y","%d %b %Y"],',
        '  "output":"date"|"timestamp"}. Tries each strptime format in order.',
        '- map_values: {"op":"map_values","table":{"From":"to"},',
        '  "unmapped":"ask_admin"|"error"|"null"|"keep","case_insensitive":true|false}.',
        '- lookup: {"op":"lookup","prefix_length":3,"table":{"001":"account"},"unmapped":...}.',
        "  Maps the first N characters of the value, for example a record Id prefix to a type.",
        '- split: {"op":"split","separator":",","index":0}.',
        '- concat: {"op":"concat","fields":["FirstName","LastName"],"separator":" "}.',
        "  Joins fields of the same source record.",
        '- default: {"op":"default","value":"USD"}. Used when the value is empty.',
        '- normalize_phone: {"op":"normalize_phone","default_country_code":"1"}. Gives E.164.',
        "Empty values pass through every step except default and concat as null.",
    ]
)

MAX_STEPS = 8
UNMAPPED_MODES = {"ask_admin", "error", "null", "keep"}
CAST_TYPES = {"string", "integer", "number", "boolean", "date", "timestamp"}
DATE_FORMAT = re.compile(r"^(?:%[YmdbByHMS]|[/\-., :T])+$")
SCALAR = (str, int, float, bool, type(None))

# op name -> {parameter: required?}
OPS: dict[str, dict[str, bool]] = {
    "copy": {},
    "trim": {},
    "case": {"to": True},
    "cast": {"to": True},
    "parse_date": {"formats": True, "output": False},
    "map_values": {"table": True, "unmapped": False, "case_insensitive": False},
    "lookup": {"prefix_length": True, "table": True, "unmapped": False},
    "split": {"separator": True, "index": True},
    "concat": {"fields": True, "separator": False},
    "default": {"value": True},
    "normalize_phone": {"default_country_code": False},
}


class RuleFailure(Exception):
    """A value could not be transformed. The message never contains the value itself."""


class UnmappedValue(RuleFailure):
    """A map_values or lookup step met a value with no entry and unmapped='ask_admin'."""


def _table_errors(step: dict[str, Any], where: str) -> list[str]:
    table = step.get("table")
    if not isinstance(table, dict) or not table:
        return [f"{where}: 'table' must be a non-empty object."]
    errors = []
    if not all(isinstance(k, str) and isinstance(v, SCALAR) for k, v in table.items()):
        errors.append(f"{where}: 'table' keys must be strings and values must be scalars.")
    if step.get("unmapped", "error") not in UNMAPPED_MODES:
        errors.append(f"{where}: 'unmapped' must be one of {sorted(UNMAPPED_MODES)}.")
    return errors


def validate_rule(rule: Any) -> list[str]:
    """Return every problem with a rule. An empty list means it is safe to run."""
    if not isinstance(rule, list):
        return ["A rule must be a list of steps."]
    if len(rule) > MAX_STEPS:
        return [f"A rule may have at most {MAX_STEPS} steps."]
    errors: list[str] = []
    for i, step in enumerate(rule):
        where = f"step {i + 1}"
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            errors.append(f"{where}: each step must be an object with an 'op'.")
            continue
        op = step["op"]
        if op not in OPS:
            errors.append(f"{where}: unknown operation {op!r}. Allowed: {sorted(OPS)}.")
            continue
        where = f"{where} ({op})"
        allowed = OPS[op]
        for key in step:
            if key != "op" and key not in allowed:
                errors.append(f"{where}: unexpected parameter {key!r}.")
        for key, required in allowed.items():
            if required and key not in step:
                errors.append(f"{where}: missing parameter {key!r}.")
        if any(e.startswith(where) for e in errors):
            continue
        if op == "case" and step["to"] not in ("upper", "lower", "title"):
            errors.append(f"{where}: 'to' must be upper, lower or title.")
        elif op == "cast" and step["to"] not in CAST_TYPES:
            errors.append(f"{where}: 'to' must be one of {sorted(CAST_TYPES)}.")
        elif op == "parse_date":
            formats = step["formats"]
            if (
                not isinstance(formats, list)
                or not 1 <= len(formats) <= 6
                or not all(isinstance(f, str) and DATE_FORMAT.match(f) for f in formats)
            ):
                errors.append(
                    f"{where}: 'formats' must be 1 to 6 strptime patterns using only "
                    "%Y %y %m %d %b %B %H %M %S and separators."
                )
            if step.get("output", "date") not in ("date", "timestamp"):
                errors.append(f"{where}: 'output' must be date or timestamp.")
        elif op == "map_values":
            errors += _table_errors(step, where)
            if not isinstance(step.get("case_insensitive", False), bool):
                errors.append(f"{where}: 'case_insensitive' must be true or false.")
        elif op == "lookup":
            errors += _table_errors(step, where)
            n = step["prefix_length"]
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 18:
                errors.append(f"{where}: 'prefix_length' must be a whole number from 1 to 18.")
        elif op == "split":
            if not isinstance(step["separator"], str) or not step["separator"]:
                errors.append(f"{where}: 'separator' must be a non-empty string.")
            if not isinstance(step["index"], int) or isinstance(step["index"], bool):
                errors.append(f"{where}: 'index' must be a whole number.")
        elif op == "concat":
            fields = step["fields"]
            if (
                not isinstance(fields, list)
                or not 1 <= len(fields) <= 6
                or not all(isinstance(f, str) and NAME.match(f) for f in fields)
            ):
                errors.append(f"{where}: 'fields' must be 1 to 6 field API names.")
            if not isinstance(step.get("separator", " "), str):
                errors.append(f"{where}: 'separator' must be a string.")
        elif op == "default" and not isinstance(step["value"], SCALAR):
            errors.append(f"{where}: 'value' must be a scalar.")
        elif op == "normalize_phone":
            code = step.get("default_country_code", "1")
            if not isinstance(code, str) or not re.fullmatch(r"[1-9]\d{0,2}", code):
                errors.append(f"{where}: 'default_country_code' must be 1 to 3 digits.")
    return errors


def asks_admin(rule: list[dict[str, Any]]) -> bool:
    """True when the rule defers unmapped values to the administrator."""
    return any(
        s.get("op") in ("map_values", "lookup") and s.get("unmapped") == "ask_admin" for s in rule
    )


def concat_fields(rule: list[dict[str, Any]]) -> list[str]:
    return [f for s in rule if s.get("op") == "concat" for f in s.get("fields", [])]


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_date(text: str) -> date:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        raise RuleFailure("value is not an ISO date") from None


def _cast(value: Any, to: str) -> Any:
    text = str(value).strip()
    if to == "string":
        return str(value)
    if to == "boolean":
        if isinstance(value, bool):
            return value
        if text.lower() in ("true", "yes", "1"):
            return True
        if text.lower() in ("false", "no", "0"):
            return False
        raise RuleFailure("value is not a boolean")
    if to in ("integer", "number"):
        try:
            number = float(text.replace(",", ""))
        except ValueError:
            raise RuleFailure("value is not a number") from None
        if to == "integer":
            if number != int(number):
                raise RuleFailure("value is not a whole number")
            return int(number)
        return number
    if to == "date":
        return _to_date(text).isoformat()
    return f"{_to_date(text).isoformat()}T00:00:00Z" if len(text) <= 10 else _timestamp(text)


def _timestamp(text: str) -> str:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise RuleFailure("value is not an ISO timestamp") from None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _lookup(key: str, step: dict[str, Any], original: Any) -> Any:
    table = step["table"]
    if step.get("case_insensitive"):
        table = {k.lower(): v for k, v in table.items()}
        key = key.lower()
    if key in table:
        return table[key]
    mode = step.get("unmapped", "error")
    if mode == "keep":
        return original
    if mode == "null":
        return None
    if mode == "ask_admin":
        raise UnmappedValue("value has no entry in the table; the administrator must decide")
    raise RuleFailure("value has no entry in the table")


def _phone(value: Any, country_code: str) -> str:
    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+{country_code}{digits}"
    if len(digits) == 10 + len(country_code) and digits.startswith(country_code):
        return f"+{digits}"
    raise RuleFailure("value is not a complete phone number")


def apply_rule(rule: list[dict[str, Any]], value: Any, record: dict[str, Any] | None = None) -> Any:
    """Run a validated rule on one value. `record` supplies sibling fields for concat."""
    for step in rule:
        op = step["op"]
        if op == "default":
            if _empty(value):
                value = step["value"]
            continue
        if op == "concat":
            parts = [(record or {}).get(f) for f in step["fields"]]
            joined = step.get("separator", " ").join(str(p) for p in parts if not _empty(p))
            value = joined or None
            continue
        if _empty(value):
            value = None
            continue
        if op == "copy":
            pass
        elif op == "trim":
            value = str(value).strip()
        elif op == "case":
            value = getattr(str(value), step["to"])()
        elif op == "cast":
            value = _cast(value, step["to"])
        elif op == "parse_date":
            value = _parse_date(str(value).strip(), step)
        elif op == "map_values":
            value = _lookup(str(value), step, value)
        elif op == "lookup":
            value = _lookup(str(value)[: step["prefix_length"]], step, value)
        elif op == "split":
            pieces = str(value).split(step["separator"])
            try:
                value = pieces[step["index"]].strip()
            except IndexError:
                raise RuleFailure("value has too few parts to split") from None
        elif op == "normalize_phone":
            value = _phone(value, step.get("default_country_code", "1"))
    return value


def _parse_date(text: str, step: dict[str, Any]) -> str:
    for fmt in step["formats"]:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if step.get("output", "date") == "timestamp":
            return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        return parsed.date().isoformat()
    raise RuleFailure("value matches none of the date formats")


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def check_target_value(field: dict[str, Any], value: Any) -> str | None:
    """Why a transformed value does not fit a target field, or None if it fits."""
    if _empty(value):
        return "required value is missing" if field["required"] else None
    kind = field["type"]
    if kind == "enum":
        return None if value in field["values"] else "value is not one of the allowed values"
    if kind == "numeric":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return None if ok else "value is not a number"
    if not isinstance(value, str):
        return "value is not text"
    if kind == "email":
        return None if EMAIL.match(value) else "value is not an email address"
    if kind == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            return "value is not an ISO date"
        return None
    if kind == "timestamp":
        stamp = re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value)
        return None if stamp else "value is not an ISO UTC timestamp"
    if field["name"] == "phone":
        return None if E164.match(value) else "value is not an E.164 phone number"
    return None
