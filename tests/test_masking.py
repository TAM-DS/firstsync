from firstsync.masking import mask_records, shape


def _describe(*fields):
    return {"fields": [{"name": n, "type": t} for n, t in fields]}


def test_shape_keeps_format_and_drops_content():
    assert shape("Dana Reyes") == "Xxxx Xxxxx"
    assert shape("(512) 555-0142") == "(999) 999-9999"
    assert shape("03/14/2021") == "99/99/9999"


def test_personal_fields_are_never_returned_raw():
    describe = _describe(("FirstName", "string"), ("Email", "email"), ("Phone", "phone"))
    records = [{"FirstName": "Dana", "Email": "dana@acme.example", "Phone": "(512) 555-0142"}]
    masked, treatments = mask_records(describe, records)
    assert masked == [
        {"FirstName": "Xxxx", "Email": "xxxx@xxxx.xxxxxxx", "Phone": "(999) 999-9999"}
    ]
    assert set(treatments.values()) == {"shape"}


def test_structural_values_pass_through():
    describe = _describe(("Id", "id"), ("Amount", "currency"), ("Stage", "picklist"))
    records = [{"Id": "006000000000001AAA", "Amount": 1200.0, "Stage": "Won"}]
    masked, _ = mask_records(describe, records)
    assert masked == records


def test_long_text_becomes_a_length_summary():
    describe = _describe(("Description", "textarea"))
    masked, _ = mask_records(describe, [{"Description": "Called about pricing."}])
    assert masked == [{"Description": "[text, 21 chars]"}]


def test_hand_typed_picklist_in_a_text_field_passes_through():
    describe = _describe(("Field_7__c", "string"))
    records = [{"Field_7__c": v} for v in ["Retail", "Energy"] * 10]
    masked, treatments = mask_records(describe, records)
    assert treatments == {"Field_7__c": "categorical"}
    assert masked == records


def test_text_field_holding_emails_is_not_treated_as_a_picklist():
    describe = _describe(("Notes__c", "string"))
    records = [{"Notes__c": v} for v in ["a@x.example", "b@x.example"] * 10]
    masked, treatments = mask_records(describe, records)
    assert treatments == {"Notes__c": "shape"}
    assert all("@x.example" not in r["Notes__c"] for r in masked)


def test_unclassified_fields_are_dropped():
    masked, _ = mask_records(_describe(("Id", "id")), [{"Id": "1", "Secret": "value"}])
    assert masked == [{"Id": "1"}]


def test_nulls_stay_null():
    masked, _ = mask_records(_describe(("Email", "email")), [{"Email": None}])
    assert masked == [{"Email": None}]
