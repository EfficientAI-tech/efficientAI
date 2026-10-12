"""Parse Meta WhatsApp Cloud webhook payloads for chat eval turn completion."""

from __future__ import annotations

from typing import Any, Iterator


def summarize_meta_whatsapp_webhook(payload: dict[str, Any]) -> dict[str, int | str]:
    """Counts for logging (status-only POSTs vs real inbound messages)."""
    text_messages = 0
    statuses = 0
    phone_number_id = ""
    if not isinstance(payload, dict):
        return {"text_messages": 0, "statuses": 0, "phone_number_id": ""}
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            pid = str(metadata.get("phone_number_id") or "").strip()
            if pid:
                phone_number_id = pid
            statuses += len(value.get("statuses") or [])
            for message in value.get("messages") or []:
                if isinstance(message, dict) and (message.get("type") or "").lower() == "text":
                    text_messages += 1
    return {
        "text_messages": text_messages,
        "statuses": statuses,
        "phone_number_id": phone_number_id,
    }


def iter_meta_whatsapp_text_messages(payload: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    """Yield (phone_number_id, sender_wa_id, text_body) for each inbound text message."""
    if not isinstance(payload, dict):
        return
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            phone_number_id = str(metadata.get("phone_number_id") or "").strip()
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                if (message.get("type") or "").strip().lower() != "text":
                    continue
                text_obj = message.get("text")
                body = ""
                if isinstance(text_obj, dict):
                    body = str(text_obj.get("body") or "").strip()
                sender = str(message.get("from") or "").strip()
                if phone_number_id and sender and body:
                    yield phone_number_id, sender, body
