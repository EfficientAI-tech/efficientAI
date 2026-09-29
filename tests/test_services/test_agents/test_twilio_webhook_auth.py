from app.services.agents.twilio_webhook_auth import compute_twilio_signature, validate_twilio_request


def test_twilio_signature_known_vector():
    auth_token = "12345"
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+14158675310", "Digits": "1234", "From": "+14158675310", "To": "+18005551212"}
    sig = compute_twilio_signature(auth_token, url, params)
    assert validate_twilio_request(
        auth_token=auth_token,
        url=url,
        params=params,
        signature=sig,
    )
