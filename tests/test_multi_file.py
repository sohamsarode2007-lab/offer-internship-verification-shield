"""Several files in one check: joined text, one score, limits, no .eml mixing, duplicate-text note."""
from app.services import multi_file

LETTER = ("We are pleased to offer you the data analyst internship at Acme Data Solutions Pvt Ltd starting next month. "
          "Your duties include preparing weekly reports, cleaning datasets and attending team meetings every Monday. "
          "Please confirm your joining date by reply to the recruitment team. ")


def txt(name, body):
    return ("files", (name, body.encode(), "text/plain"))


def test_two_files_are_scored_together(api_client):
    r = api_client.post("/analyze", files=[txt("a.txt", LETTER), txt("b.txt", "Pay the registration fee of Rs 500 to confirm.")])
    assert r.status_code == 200
    body = r.json()
    assert body["risk_band"] == "high risk"   # the payment demand in the second file counts for the whole pack


def test_single_file_field_still_works(api_client):
    r = api_client.post("/analyze", files={"file": ("a.txt", LETTER.encode(), "text/plain")})
    assert r.status_code == 200


def test_more_than_five_files_is_rejected(api_client):
    r = api_client.post("/analyze", files=[txt(f"{i}.txt", LETTER + str(i)) for i in range(6)])
    assert r.status_code == 400 and "at most 5" in r.json()["detail"]


def test_eml_cannot_be_mixed_with_other_files(api_client):
    r = api_client.post("/analyze", files=[txt("a.txt", LETTER), ("files", ("m.eml", b"From: a@b.example\r\n\r\nhi", "message/rfc822"))])
    assert r.status_code == 422 and ".eml on its own" in r.json()["detail"]


def test_combined_text_over_the_limit_is_rejected(api_client):
    big = ("Interview details will follow by email. " * 1000)[:30000]
    r = api_client.post("/analyze", files=[txt("a.txt", big), txt("b.txt", big + "x")])
    assert r.status_code == 413


def test_near_duplicate_files_get_a_note_and_different_files_do_not(api_client):
    dup = api_client.post("/analyze", files=[txt("a.txt", LETTER), txt("b.txt", LETTER + "Thanks.")]).json()
    assert any("almost the same text" in x["text"] for x in dup["reasons"])
    other = api_client.post("/analyze", files=[txt("a.txt", LETTER), txt("b.txt", "Quarterly sales review notes: revenue rose in the western region while costs held steady across all product lines this year.")]).json()
    assert not any("almost the same text" in x["text"] for x in other["reasons"])


def test_duplicate_note_has_no_score_effect_and_short_texts_are_ignored():
    assert multi_file.duplicate_note(["hello world", "hello world"]) is None
    assert multi_file.duplicate_note([LETTER, LETTER]) == multi_file.DUPLICATE_NOTE
    assert multi_file.jaccard(LETTER, "") == 0.0
