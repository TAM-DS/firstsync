"""Mask sampled records before they reach the model.

The model needs to see what a field looks like (a date written as text, a phone number in
four formats, a picklist typed by hand). It does not need the values themselves. So:

- personal values keep their shape and lose their content ("Dana Reyes" -> "Xxxx Xxxxx")
- long free text becomes a length summary
- structural values (ids, numbers, dates, booleans, picklists) pass through
- a text field with only a few repeating values is treated as a hand-typed picklist and
  passes through, because those values are exactly what a mapping has to be built on
"""

from __future__ import annotations

import re
from typing import Any

PASS_TYPES = {
    "id",
    "reference",
    "boolean",
    "int",
    "double",
    "currency",
    "percent",
    "date",
    "datetime",
    "time",
    "picklist",
    "multipicklist",
}
SHAPE_TYPES = {"email", "phone", "address", "url"}
SUMMARY_TYPES = {"textarea"}

PERSONAL_NAME = re.compile(
    r"(^|_)(name|firstname|lastname|first_name|last_name|street|city|postalcode|zip)(__c)?$",
    re.IGNORECASE,
)
EMAIL_VALUE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

CATEGORICAL_MAX_DISTINCT = 12


def shape(value: str) -> str:
    """Replace letters with x/X and digits with 9; keep punctuation and spacing."""
    out = []
    for ch in value:
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("X" if ch.isupper() else "x")
        else:
            out.append(ch)
    return "".join(out)


def _is_categorical(values: list[Any]) -> bool:
    present = [v for v in values if v not in (None, "")]
    if len(present) < 2:
        return False
    distinct = {str(v) for v in present}
    if any(EMAIL_VALUE.match(v) for v in distinct):
        return False
    return len(distinct) <= CATEGORICAL_MAX_DISTINCT and len(present) >= 2 * len(distinct)


def field_treatments(describe: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, str]:
    """Decide, per field, how its values are handled: pass, categorical, shape or summary."""
    treatments: dict[str, str] = {}
    for field in describe.get("fields", []):
        name = field["name"]
        ftype = field.get("type", "string")
        if ftype in PASS_TYPES:
            treatments[name] = "pass"
        elif ftype in SUMMARY_TYPES:
            treatments[name] = "summary"
        elif ftype in SHAPE_TYPES or PERSONAL_NAME.search(name):
            treatments[name] = "shape"
        elif _is_categorical([r.get(name) for r in records]):
            treatments[name] = "categorical"
        else:
            treatments[name] = "shape"
    return treatments


def display(treatment: str, value: Any) -> Any:
    """How one value is shown to the model, given its field's treatment."""
    return _apply(treatment, value)


def _apply(treatment: str, value: Any) -> Any:
    if value is None or treatment in ("pass", "categorical"):
        return value
    text = str(value)
    if treatment == "summary":
        return f"[text, {len(text)} chars]"
    return shape(text)


def mask_records(
    describe: dict[str, Any], records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return masked copies of the records and the treatment applied to each field.

    A field that is not in the describe result is dropped: if we cannot classify it,
    it does not go to the model.
    """
    treatments = field_treatments(describe, records)
    masked = [
        {name: _apply(treatments[name], record.get(name)) for name in treatments if name in record}
        for record in records
    ]
    return masked, treatments
