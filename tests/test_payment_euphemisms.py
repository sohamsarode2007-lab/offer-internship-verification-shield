"""Disguised-fee phrasing seen in Indian internship/job scams (synthetic sentences only).

Every positive case must be reported as a payment demand; every negative case
must not. Expected results were decided by hand before the patterns were written.
"""
import pytest

from app.services.payment_detection import detect_payment_demand


def _status(text: str) -> str:
    return detect_payment_demand({"raw_text": text})["status"]


DEMANDS = [
    # disguised fee names
    "A courier insurance charge of Rs 3,500 is applicable for the laptop dispatch.",
    "Pay the BGV charges of Rs 2000 to start the background verification.",
    "Slot booking fee of Rs 999 is needed to reserve your seat.",
    "Seat confirmation fees must be paid today.",
    "An internship certificate fee of Rs 499 is payable before the start date.",
    "Training-cum-internship fee of Rs 5,000 is to be paid by the selected candidate.",
    "The medical test deposit of Rs 1,500 must be sent to the HR account.",
    "Bond notarization fee of Rs 750 is payable by the candidate.",
    "ID card charges of Rs 300 will be collected from you.",
    "Offer letter charges of Rs 1,000 apply to selected candidates.",
    "An interview fee of Rs 250 is required to attend the final round.",
    "Pay a refundable software license fee to get your login.",
    # amounts without the Rs prefix
    "Kindly pay 2000 rupees to confirm your selection.",
    "Transfer 1,500 rupees to the account given below.",
    # amount-first phrasing
    "Rs 4,500 is payable by the candidate before joining.",
    # Hinglish
    "Selection ke liye 500 rupaye bhejiye is number par.",
    "Registration ke liye fees bharna hoga.",
    # sentence boundary after company suffix
    "No hidden charges at Acme Pvt. Ltd. Pay 2000 rupees for BGV charges.",
    # disguised fee in same sentence as "we will provide"
    "We will provide your offer letter once you pay 2000 rupees for BGV charges.",
]

NOT_DEMANDS = [
    "No interview fee, no certificate fee and no courier charges apply.",
    "We never ask for BGV charges or slot booking fees from candidates.",
    "The company bears the courier insurance charge for your laptop.",
    "Background verification will be done by the company at its own cost.",
    "Your stipend of Rs 15,000 will be credited monthly.",
    "Medical test is not required for this role.",
    "Please carry your ID card on the first day.",
    "The interview is on Monday; the certificate will be issued after completion.",
    "Offer letter will be shared after you accept.",
    "Reimbursement of travel up to Rs 2,000 is provided by the company.",
    "Fees bharna nahi hai, selection free hai.",
    "Koi fees nahi lagegi is internship mein.",
    "The internship fee is waived for all selected candidates.",
    "Your stipend is 15000 rupees and we will pay it every month.",
]


@pytest.mark.parametrize("text", DEMANDS)
def test_disguised_fee_is_a_demand(text):
    assert _status(text) == "fail", text


@pytest.mark.parametrize("text", NOT_DEMANDS)
def test_legitimate_or_negated_mention_is_not_a_demand(text):
    assert _status(text) == "pass", text
