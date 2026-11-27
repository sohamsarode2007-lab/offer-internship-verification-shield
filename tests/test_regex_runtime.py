"""Long runs of spaces or letters must not make the text rules slow (CodeQL 'polynomial regular expression')."""
import time

from app.services import community_reports as cr
from app.services import fact_extraction, payment_detection

N = 60_000
LIMIT_SECONDS = 1.0


def _fast(fn):
    start = time.perf_counter()
    fn()
    assert time.perf_counter() - start < LIMIT_SECONDS


def test_account_number_rule_is_linear_on_long_whitespace():
    _fast(lambda: fact_extraction.extract_facts("account" + " " * N + "x"))


def test_redaction_amount_rules_are_linear_on_long_whitespace():
    _fast(lambda: cr.redact_text("salary" + " " * N + "x Rs" + " " * N + "y"))


def test_sentence_split_is_linear_on_long_letter_runs():
    _fast(lambda: payment_detection.sentence_spans("a" * N + ". " + "b" * N + ". Next"))


def test_the_rewritten_patterns_still_redact_and_extract_the_same_things():
    assert "<AMOUNT>" in cr.redact_text("Pay Rs. 5,000 now; stipend is 15000; fee: 2500")
    assert "Rs" not in cr.redact_text("Rs 5000").replace("<AMOUNT>", "")
    facts = fact_extraction.extract_facts("Send money to account number: 123456789012 today")
    assert "123456789012" in str(facts)
    assert payment_detection.sentence_spans("Acme Pvt. Ltd. Registration fee is Rs 500.")[1][0] > 0   # split after Ltd.
