"""Integration coverage for safety actions in the public analyze response."""


def test_analyze_returns_safety_actions_without_offer_text(api_client):
    secret = "Rahul Sharma 9876543210"
    response = api_client.post(
        "/analyze",
        data={
            "text": f"{secret}. Pay Rs 500 as a registration fee before joining.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "payment" in [action["id"] for action in body["safety_actions"]]
    assert any(action["id"] == "report" for action in body["safety_actions"])
    assert secret not in response.text
