"""Unit tests for individual rules: brand lookalikes and the extra payment phrases."""
import pytest

from app.services import domain_verification as dv, payment_detection as pd


# --- Brand lookalike rule ---------------------------------------------------

@pytest.mark.parametrize("domain", ["amazing.in", "tcsion.com", "careers.tcs.com", "iitbhu.ac.in", "nitw.ac.in"])
def test_not_lookalike(domain):
    assert dv.find_lookalike(domain) is None


@pytest.mark.parametrize("domain", ["lnfosys.com", "infosyss.com", "tcs-careers.in", "tcs.co.in"])
def test_is_lookalike(domain):
    assert dv.find_lookalike(domain) is not None


def test_tcsion_is_official():
    assert any(domain == "tcsion.com" for domain in dv.BRAND_OFFICIAL_DOMAINS["tcs"])
    assert dv.find_lookalike("tcsion.com") is None


# --- Extra payment phrases: one demand (fail) and one negated (pass) each ---

PAYMENT_PAIRS = [
    ("background check fee",
     "Please pay the background check fee of Rs 750 before onboarding.",
     "We do not charge any background check fee."),
    ("document verification fee",
     "A document verification fee of Rs 300 is payable before joining.",
     "There is no document verification fee for candidates."),
    ("onboarding fee",
     "Kindly clear the onboarding fee of Rs 1,200 to activate your account.",
     "We never collect an onboarding fee from interns."),
    ("laptop fee",
     "You must cover the laptop fee of Rs 2,500 before dispatch.",
     "We do not charge any laptop fee."),
    ("transfer Rs N",
     "Transfer Rs 999 to our account to confirm your slot.",
     "Candidates are never asked to transfer Rs 999 or any other amount."),
]


def _status(text):
    return pd.detect_payment_demand({"raw_text": text})["status"]


@pytest.mark.parametrize("name,demand,negated", PAYMENT_PAIRS, ids=[p[0] for p in PAYMENT_PAIRS])
def test_extra_phrase_demand_fails(name, demand, negated):
    assert _status(demand) == "fail"


@pytest.mark.parametrize("name,demand,negated", PAYMENT_PAIRS, ids=[p[0] for p in PAYMENT_PAIRS])
def test_extra_phrase_negated_passes(name, demand, negated):
    assert _status(negated) == "pass"
