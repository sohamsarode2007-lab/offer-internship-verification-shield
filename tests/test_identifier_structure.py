"""PAN, Udyam and payments-bank IFSC structure checks. Offline; every company is fictional."""
import pytest

from app.services import fact_extraction, gstin_verification as gv, payment_detection

NAME = "Emberlake Analytics Pvt. Ltd."
GSTIN = "07AAFCE4321L1ZO"          # embeds PAN AAFCE4321L (holder type C)
GOOD_PAN = "AAFCE4321L"


def check(text):
    return gv.verify_gstin(fact_extraction.extract_facts(text))


def payment(text):
    return payment_detection.detect_payment_demand(fact_extraction.extract_facts(text))


# ---- PAN -------------------------------------------------------------------------------------
def test_valid_company_pan_matching_gstin_adds_no_problem():
    result = check(f"{NAME}\nGSTIN: {GSTIN}\nPAN: {GOOD_PAN}")
    assert result["status"] == "insufficient_information"          # valid structure, no registry record
    assert {"type": "PAN", "value": GOOD_PAN} in result["identifiers"]


def test_malformed_pan_fails():
    result = check(f"{NAME}\nPAN: ABCDE12345")
    assert result["status"] == "fail" and "does not match the PAN format" in result["details"]


def test_individual_pan_on_a_company_name_fails():
    result = check(f"{NAME}\nPAN: ABCPE1234F")                       # 4th character P = individual
    assert result["status"] == "fail" and "holder-type 'P' instead of 'C'" in result["details"]


def test_pan_that_differs_from_the_gstin_pan_fails():
    result = check(f"{NAME}\nGSTIN: {GSTIN}\nPAN: ABCCE1234F")
    assert result["status"] == "fail" and "differs from the PAN inside GSTIN" in result["details"]


@pytest.mark.parametrize("text", ["Reference ABCDE1234F for the file.", "PAN: Details to follow",
                                  "Pan card copy required at joining"])
def test_unlabelled_or_wordlike_pan_is_not_extracted(text):
    result = check(text)
    assert result["identifier_present"] is False


# ---- Udyam -----------------------------------------------------------------------------------
def test_valid_udyam_format_is_noted_not_verified():
    result = check("Enterprise registered as UDYAM-MH-26-0123456.")
    assert result["status"] == "insufficient_information"
    assert "self-declared and are not verified here" in result["details"]


def test_udyam_with_spaces_is_normalised():
    result = check("Registered as UDYAM MH 26 0123456.")
    assert {"type": "UDYAM", "value": "UDYAM-MH-26-0123456"} in result["identifiers"]


def test_malformed_udyam_fails():
    result = check("Enterprise registered as UDYAM-MH-26-01234.")
    assert result["status"] == "fail" and "does not match the UDYAM-XX-00-0000000 format" in result["details"]


def test_word_udyam_without_number_is_not_an_identifier():
    assert check("We support Udyam registered businesses.")["identifier_present"] is False


# ---- Payments-bank IFSC ----------------------------------------------------------------------
DEMAND = "Pay Rs 5000 as security deposit to confirm your seat. Account 123456789012, IFSC {ifsc}."


def test_payments_bank_ifsc_is_noted_in_a_payment_demand():
    result = payment(DEMAND.format(ifsc="PYTM0123456"))
    assert result["status"] == "fail"
    assert "payments-bank account (Paytm Payments Bank)" in result["details"]
    assert "PYTM0123456" not in result["details"]                   # the code is never echoed back


def test_ordinary_bank_ifsc_adds_no_note():
    result = payment(DEMAND.format(ifsc="HDFC0001234"))
    assert result["status"] == "fail" and "payments-bank" not in result["details"]


def test_payments_bank_ifsc_without_a_demand_adds_no_note():
    result = payment("Our payroll is processed monthly. Reference IFSC PYTM0123456 for the stipend account.")
    assert result["status"] == "pass" and "payments-bank" not in result["details"]
