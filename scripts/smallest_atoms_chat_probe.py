#!/usr/bin/env python3

"""

Log Smallest Atoms chat (LiveKit data channel) for protocol discovery.



Usage:

  export SMALLEST_API_KEY=...

  python scripts/smallest_atoms_chat_probe.py --agent-id <atoms_agent_id> --message "Hello"



Optional:

  --timeout 45 --json-log /tmp/smallest_events.jsonl



Each inbound event: ISO time, classified kind, event type, JSON payload.

Capture a good session into tests/fixtures/smallest_atoms_chat/<name>.json

and extend smallest_atoms_protocol.py.

"""



from __future__ import annotations



import argparse

import json

import sys

from datetime import datetime, timezone

from pathlib import Path



_REPO_ROOT = Path(__file__).resolve().parents[1]

if str(_REPO_ROOT) not in sys.path:

    sys.path.insert(0, str(_REPO_ROOT))



from app.services.agents.smallest_atoms_chat import SmallestAtomsChatSession

from app.services.agents.smallest_atoms_protocol import (

    classify_inbound_event,

    event_type,

)





def _parse_args() -> argparse.Namespace:

    p = argparse.ArgumentParser(description="Probe Smallest Atoms chat (LiveKit)")

    p.add_argument("--agent-id", required=True)

    p.add_argument("--api-key", default=None, help="Defaults to SMALLEST_API_KEY env")

    p.add_argument("--message", default="Hello, this is a connectivity probe.")

    p.add_argument("--timeout", type=float, default=60.0)

    p.add_argument("--json-log", type=Path, default=None)

    return p.parse_args()





def main() -> int:

    import os



    args = _parse_args()

    api_key = (args.api_key or os.environ.get("SMALLEST_API_KEY") or "").strip()

    if not api_key:

        print("Set SMALLEST_API_KEY or pass --api-key", file=sys.stderr)

        return 2



    inbound: list[dict] = []

    log_path = args.json_log



    def on_event(event: dict) -> None:

        kind = classify_inbound_event(event)

        etype = event_type(event)

        stamp = datetime.now(timezone.utc).isoformat()

        print(f"{stamp}  {kind.value:16}  {etype or '(no type)'}")

        print(json.dumps(event, ensure_ascii=False))

        inbound.append(event)

        if log_path:

            with log_path.open("a", encoding="utf-8") as fh:

                fh.write(json.dumps({"ts": stamp, "kind": kind.value, "event": event}) + "\n")



    session = SmallestAtomsChatSession(

        api_key,

        args.agent_id,

        timeout=args.timeout,

        on_inbound_event=on_event,

    )



    try:

        reply = session.send_user_message(args.message)

        print(f"\n[assistant reply]\n{reply}\n")

        print(f"[session meta] {session.meta}")

    except Exception as exc:

        print(f"Probe failed: {exc}", file=sys.stderr)

        return 1

    finally:

        session.close()



    unknown = sorted(

        {event_type(e) for e in inbound if classify_inbound_event(e).name == "UNKNOWN" and event_type(e)}

    )

    if unknown:

        print(f"\nUnclassified types (extend smallest_atoms_protocol): {unknown}")

    return 0





if __name__ == "__main__":

    raise SystemExit(main())

