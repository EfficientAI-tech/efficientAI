"""Shared JSON-recovery helpers for LLM workers.

The LLM-based diariser and evaluator both consume structured JSON from
chat-completion responses, and both run into the same family of
failure modes:

* The model wraps the answer in a ``{"turns": [...]}`` /
  ``{"metrics": {...}}`` envelope even when the prompt asked for a bare
  shape.
* The response is truncated mid-string when ``max_output_tokens`` is
  exhausted (notably on Gemini 2.5 where internal "thinking" tokens
  are deducted from the output budget) and standard ``json.loads``
  fails with ``Unterminated string`` or ``Expecting value``.

Centralising the recovery logic in one module avoids the historical
drift between the diariser and evaluator parsers (e.g. the evaluator
already handled truncation but the diariser did not, so the diariser
would hard-fail on responses the evaluator would have salvaged).
"""

from __future__ import annotations

from typing import Optional


def repair_truncated_json(text: str) -> Optional[str]:
    """Best-effort repair of a JSON document that was cut off mid-output.

    Handles the common Gemini 2.5 / 3.x failure mode where
    ``max_output_tokens`` is exhausted (often by internal thinking
    tokens) and the response stops mid-string, e.g.::

        {"a": 1, "b": "some long ration

    We walk the string, track quote/escape/bracket state, drop any
    dangling trailing key-without-value or comma, close the open
    string if needed, then close any still-open ``{`` / ``[`` in
    reverse order. Returns the repaired text on success or ``None``
    if nothing salvageable is found.

    The repair is intentionally conservative — when the cut-off
    happens before any complete key:value pair has been emitted, we
    close the open string and brackets verbatim (yielding e.g. ``{}``
    or ``[]``) rather than guessing at structure. The caller decides
    whether an empty payload is useful or should be surfaced as a
    typed error.
    """
    if not text:
        return None

    in_string = False
    escape = False
    stack: list[str] = []
    last_safe = -1  # index just after the last fully-parsed key:value pair

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    stack.pop()
                # A balanced root object/array is itself a safe cut-point.
                if not stack:
                    last_safe = i + 1
            elif ch == "," and len(stack) >= 1 and stack[-1] == "{":
                # Comma at object scope = previous key:value pair just closed.
                last_safe = i
            elif ch == "," and len(stack) >= 1 and stack[-1] == "[":
                # Comma at array scope = previous element just closed.
                # Treat this as a safe cut-point so a truncated array of
                # turn objects can recover everything up to the last
                # fully-emitted entry instead of falling all the way
                # back to ``[]``.
                last_safe = i
        i += 1

    if last_safe <= 0:
        # No complete key:value pair seen yet — try to close an open
        # string and unbalanced brackets to at least get an empty
        # object / array. The caller's downstream validation will
        # decide whether that's useful.
        repaired = text
        if in_string:
            repaired += '"'
        for opener in reversed(stack):
            repaired += "}" if opener == "{" else "]"
        return repaired if repaired != text else None

    # Truncate to the last clean point and re-close the outer containers.
    head = text[:last_safe].rstrip().rstrip(",")
    # Re-derive bracket stack for the trimmed head, since the outer
    # ``stack`` reflects the full (truncated) text rather than the
    # trimmed prefix.
    head_stack: list[str] = []
    in_string = False
    escape = False
    for ch in head:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                head_stack.append(ch)
            elif ch in "}]" and head_stack:
                head_stack.pop()

    closers = "".join("}" if op == "{" else "]" for op in reversed(head_stack))
    return head + closers
