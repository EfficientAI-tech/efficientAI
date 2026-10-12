from app.services.telephony.meta_whatsapp_webhook_setup import ensure_waba_subscribed_to_app


def test_ensure_waba_subscribed_posts(monkeypatch):
    calls: list[str] = []

    class FakeResponse:
        status_code = 200
        text = '{"success":true}'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, params=None):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.telephony.meta_whatsapp_webhook_setup.httpx.Client",
        FakeClient,
    )
    assert ensure_waba_subscribed_to_app("1531697088984781", "token123")
    assert calls[0].endswith("/1531697088984781/subscribed_apps")
