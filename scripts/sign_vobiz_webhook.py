#!/usr/bin/env python3
"""Sign a Vobiz/Plivo-style voice webhook for local curl/Postman (V1 + optional raw-body HMAC).

The callback URL must match config ``vobiz.webhook_base_url`` + path (same URI Vobiz uses when signing).

Examples:

  # Answer webhook (platform token; include ParentAuthID if Vobiz sends it)
  python scripts/sign_vobiz_webhook.py \\
    --url 'https://YOUR.ngrok-free.app/api/v1/telephony/vobiz/webhooks/answer' \\
    --token "$VOBIZ_AUTH_TOKEN" \\
    --param 'CallUUID=test-uuid' \\
    --param 'To=+919876543210' \\
    --param 'From=+911234567890' \\
    --param 'CallStatus=ringing' \\
    --param 'Direction=inbound' \\
    --param 'ParentAuthID=MA_XXXXXXXX'

  # Quote + in zsh/bash: --param 'To=+91...'

For raw-body HMAC (some X-Vobiz-Signature deliveries), pass the exact body bytes file:

  python scripts/sign_vobiz_webhook.py --raw-body-file /tmp/body.txt --token "$VOBIZ_AUTH_TOKEN"
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import sys
from pathlib import Path
from urllib.parse import urlencode

# Repo root on PYTHONPATH when invoked as: python scripts/sign_vobiz_webhook.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.telephony.webhook_signature_v1 import compute_plivo_v1_webhook_signature


def _parse_params(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in pairs:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"Invalid --param (expected Key=Value): {item!r}")
        params[key] = value
    return params


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign Vobiz/Plivo voice webhooks for local testing")
    parser.add_argument(
        "--url",
        help="Full webhook URL (scheme + host + path + optional ?query)",
    )
    parser.add_argument("--token", required=True, help="Vobiz auth_token for the signing account")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Form field Key=Value (repeat; use quotes for + in shell)",
    )
    parser.add_argument(
        "--header",
        choices=("vobiz", "plivo"),
        default="vobiz",
        help="Signature header name (default: X-Vobiz-Signature)",
    )
    parser.add_argument(
        "--raw-body-file",
        type=Path,
        help="If set, print HMAC-SHA256 hex over file bytes (X-Vobiz-Signature trunk-style)",
    )
    args = parser.parse_args()

    header_name = "X-Vobiz-Signature" if args.header == "vobiz" else "X-Plivo-Signature"

    if args.raw_body_file:
        body = args.raw_body_file.read_bytes()
        sig_hex = hmac.new(args.token.encode("utf-8"), body, hashlib.sha256).hexdigest()
        print(f"{header_name} (raw-body HMAC-SHA256 hex): {sig_hex}")
        print(f"Body length: {len(body)} bytes")
        return

    if not args.url:
        raise SystemExit("--url is required unless --raw-body-file is used")

    params = _parse_params(args.param)
    sig_v1 = compute_plivo_v1_webhook_signature(args.token, args.url, params)
    body = urlencode(params)

    print(f"{header_name} (Plivo V1): {sig_v1}")
    print()
    print("curl:")
    print(f"curl -sS -X POST '{args.url}' \\")
    print("  -H 'Content-Type: application/x-www-form-urlencoded' \\")
    print(f"  -H '{header_name}: {sig_v1}' \\")
    print(f"  --data-raw '{body}'")
    print()
    raw_sig = hmac.new(args.token.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    print(f"{header_name} (raw-body HMAC-SHA256 hex of urlencoded body): {raw_sig}")


if __name__ == "__main__":
    main()
