from app.services.agents.chat_production_leg import _live_messaging_failure_detail
from app.services.agents.meta_whatsapp_inbound import (
    iter_meta_whatsapp_text_messages,
    summarize_meta_whatsapp_webhook,
)


def test_summarize_meta_whatsapp_webhook():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "1395406326980468"},
                            "statuses": [{"status": "delivered"}],
                            "messages": [
                                {"from": "917051228092", "type": "text", "text": {"body": "hi"}}
                            ],
                        }
                    }
                ]
            }
        ]
    }
    s = summarize_meta_whatsapp_webhook(payload)
    assert s["text_messages"] == 1
    assert s["statuses"] == 1
    assert s["phone_number_id"] == "1395406326980468"


def test_iter_meta_whatsapp_text_messages():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "1395406326980468"},
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "type": "text",
                                    "text": {"body": "Agent reply here"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    rows = list(iter_meta_whatsapp_text_messages(payload))
    assert rows == [("1395406326980468", "919876543210", "Agent reply here")]


def test_live_messaging_failure_detail_whatsapp_not_twilio():
    detail = _live_messaging_failure_detail("messaging_meta_whatsapp_send_only")
    assert "WhatsApp" in detail
    assert "Twilio" not in detail
    assert "Meta" in detail
