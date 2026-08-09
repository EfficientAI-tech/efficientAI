#!/usr/bin/env python3
"""Generate a single Excalidraw file with all call-import architecture diagrams."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from excalidraw_builder import ExcalidrawBuilder

OUT = Path(__file__).resolve().parent.parent / "docs" / "diagrams" / "excalidraw"
COMBINED = OUT / "call-import-architecture.excalidraw"

# Palette
C_API = "#d0bfff"
C_WORKER = "#a5d8ff"
C_REDIS = "#ffc9c9"
C_CATALOG = "#b2f2bb"
C_SHARD = "#96f2d7"
C_BLOB = "#ffec99"
C_EXT = "#ffd8a8"
C_K8S = "#e7f5ff"
C_NOTE = "#fff3bf"

W = 1500
SECTION_GAP = 100


def draw_platform_architecture(b: ExcalidrawBuilder, y: float) -> float:
    y = b.subtitle("Kubernetes deployment with catalog DB, 4 data shards, Redis fair-share", y)

    cluster_y = y
    y += 8

    row1 = b.row_boxes(
        y,
        [
            ("API\n3 replicas", C_API),
            ("worker-imports\n8–16 pods × 16 threads\nimports · diarization · eval", C_WORKER),
            ("worker\naudio-metrics\nPraat / UTMOS / torch", C_WORKER),
            ("Redis\nCelery broker\ninflight counters", C_REDIS),
            ("Prometheus\n+ KEDA", C_K8S),
        ],
        box_w=240,
        box_h=110,
        gap=36,
        font_size=16,
    )
    y = max(r[1] + r[3] for r in row1) + 64

    cat_x = (W - 360) / 2
    _, _, cy, _, ch = b.box(
        cat_x,
        y,
        360,
        100,
        "Catalog Postgres — efficientai_catalog\nCallImport · CallImportEvaluation · metrics · shard registry",
        bg=C_CATALOG,
        font_size=17,
    )
    y = cy + ch + 48

    shard_rects = b.row_boxes(
        y,
        [
            ("data-shard-01\nCallImportRow\nEvalRow", C_SHARD),
            ("data-shard-02\nCallImportRow\nEvalRow", C_SHARD),
            ("data-shard-03\nCallImportRow\nEvalRow", C_SHARD),
            ("data-shard-04\nCallImportRow\nEvalRow", C_SHARD),
        ],
        box_w=280,
        box_h=110,
        gap=40,
        font_size=16,
    )
    y = max(r[1] + r[3] for r in shard_rects) + 24
    b.frame(60, cluster_y, W - 120, y - cluster_y + 16, "Kubernetes cluster", behind=True)
    y += 32

    ext = b.row_boxes(
        y,
        [
            ("Blob storage\nS3 / GCS / Azure", C_BLOB),
            ("STT / LLM providers", C_EXT),
            ("Telephony\nExotel / Plivo", C_EXT),
        ],
        box_w=320,
        box_h=90,
        gap=60,
        font_size=17,
    )
    y = max(r[1] + r[3] for r in ext) + 48

    cx_imports = row1[1][0] + row1[1][2] / 2
    b.arrow_down(cx_imports, row1[1][1] + row1[1][3], cy - 4, label="read/write rows")
    b.arrow_down(cat_x + 180, cy + ch, shard_rects[0][1] - 4)

    return b.note(
        y,
        "Queue drain order on worker-imports: imports → diarization → eval-control → evaluations",
        bg=C_K8S,
    )


def draw_postgres_redis_flow(b: ExcalidrawBuilder, y: float) -> float:
    y = b.subtitle("Pending backlog lives in Postgres. Redis decides who may run.", y)

    steps = [
        ("1 · Write headers + rows\nPostgres catalog + data shards", C_CATALOG),
        ("2 · Fair dispatcher reads pending rows\nPostgres scatter-gather (NOT Celery queue depth)", C_SHARD),
        ("3 · acquire_eval_slot() / acquire_import_slot()\nRedis Lua script increments inflight counters", C_REDIS),
        ("4 · Enqueue Celery task + store celery_task_id\nPostgres shard row updated", C_WORKER),
        ("5 · Worker executes task\nPostgres reads/writes + STT / LLM / telephony APIs", C_WORKER),
        ("6 · release_*_slot()\nRedis decrements inflight counters", C_REDIS),
        ("7 · schedule_fair_dispatch()\nNext workspace round-robin turn", C_REDIS),
    ]
    rects = b.vertical_flow(y, steps, box_w=560, box_h=92, gap=64, font_size=17)

    y = rects[-1][1] + rects[-1][3] + 48
    return b.note(
        y,
        "Key insight: Celery queue can look empty while thousands of rows remain pending in Postgres.\n"
        "Scale on org-wide pending rows + inflight saturation — not queue depth alone.",
        bg=C_NOTE,
        font_size=16,
    )


def draw_call_import_pipeline(b: ExcalidrawBuilder, y: float) -> float:
    y = b.subtitle("Two slot types: import:* (bulk CSV) vs eval:* (transcribe + scoring chain)", y)

    stages = [
        ("Upload CSV\nAPI creates CallImport header", C_API),
        ("Materialize rows\nBulk insert onto data shards", C_SHARD),
        ("Bulk import (optional)\nprocess_call_import_row — uses import:* slots", C_REDIS),
        ("Create evaluation\nCallImportEvaluation header on catalog", C_CATALOG),
        ("Fair eval dispatch\nUses eval:* slots from here onward", C_REDIS),
        ("Transcribe / diarize\nSTT + LLM diarisation queue", C_WORKER),
        ("LLM + audio metrics\nFinal metric scores on shard row", C_WORKER),
    ]
    rects = b.vertical_flow(y, stages, box_w=560, box_h=92, gap=56, font_size=17)

    y = rects[-1][1] + rects[-1][3] + 48
    return b.note(
        y,
        "Eval-chain recording fetch uses eval:* slots (NOT import:*).\n"
        "One eval slot is held from dispatch until the row finishes scoring.",
        bg=C_NOTE,
    )


def draw_sharding_topology(b: ExcalidrawBuilder, y: float) -> float:
    y = b.subtitle("Row routing spreads 10k imports across shards (~2.5k rows each)", y)

    cat_x = (W - 420) / 2
    _, _, cy, _, ch = b.box(
        cat_x,
        y,
        420,
        110,
        "Catalog DB\nCallImport · CallImportEvaluation · metrics · call_import_shard_slices registry",
        bg=C_CATALOG,
        font_size=17,
    )
    y = cy + ch + 56

    shards = b.row_boxes(
        y,
        [
            ("data-shard-01", C_SHARD),
            ("data-shard-02", C_SHARD),
            ("data-shard-03", C_SHARD),
            ("data-shard-04", C_SHARD),
        ],
        box_w=280,
        box_h=80,
        gap=44,
        font_size=18,
    )

    for sx, sy, sw, sh in shards:
        b.arrow_down(cat_x + 210, cy + ch, sy - 4)

    y = max(s[1] + s[3] for s in shards) + 48
    y = b.note(
        y,
        "Routing formula:\n"
        "  slice_id = row_index // 500\n"
        "  shard_id = SHA256(call_import_id : slice_id) mod 4",
        bg=C_K8S,
        font_size=17,
    )
    return b.note(
        y,
        "Each pod holds SQLAlchemy pools: 1 catalog + 4 shards.\n"
        "Rule: concurrency per pod ≤ catalog pool max (pool_size + max_overflow).",
        bg=C_NOTE,
        font_size=16,
    )


def draw_fair_dispatch(b: ExcalidrawBuilder, y: float) -> float:
    y = b.subtitle("Dual 10k across two workspaces — equal fair share", y)

    ws = b.row_boxes(
        y,
        [
            ("Workspace A\n10,000 rows pending", C_API),
            ("Workspace B\n10,000 rows pending", C_API),
        ],
        box_w=360,
        box_h=100,
        gap=120,
        font_size=18,
    )
    y = max(r[1] + r[3] for r in ws) + 56

    cx = W / 2
    _, dx, dy, dw, dh = b.box(
        cx - 300,
        y,
        600,
        120,
        "Global round-robin dispatcher\n"
        "• max_workspace_turns = 999 on eval create (fill capacity)\n"
        "• max_workspace_turns = 1 after each row completes (fair refill)\n"
        "• batch_size should match eval_workspace_inflight_limit",
        bg=C_REDIS,
        font_size=16,
    )
    y = dy + dh + 48

    checks = b.row_boxes(
        y,
        [
            (
                "Eval slot checks\n(all must pass)\n"
                "workspace → org → global → job",
                C_REDIS,
            ),
            (
                "Effective parallelism\n"
                "min(job, workspace,\n"
                "global, threads)",
                C_NOTE,
            ),
        ],
        box_w=420,
        box_h=130,
        gap=80,
        font_size=17,
    )
    y = max(c[1] + c[3] for c in checks) + 48

    b.arrow_right(ws[0][0] + ws[0][2], dx - 8, ws[0][1] + ws[0][3] / 2)
    b.arrow_right(ws[1][0], dx + dw + 8, ws[1][1] + ws[1][3] / 2)
    b.arrow_down(cx, ws[0][1] + ws[0][3], dy - 4)

    return b.note(
        y,
        "Recommended (2 workspaces, 16×16 pods):\n"
        "  eval_global = 256  ·  eval_workspace = 128 each  ·  eval_job = 128\n"
        "  import_global = 96  ·  import_workspace = 48 each  ·  import_batch = 48",
        bg=C_K8S,
        font_size=16,
    )


def draw_keda_pgbouncer_roadmap(b: ExcalidrawBuilder, y: float) -> float:
    y = b.subtitle("Phase 1–3 now (no PgBouncer)  →  Phase 4–5 with PgBouncer", y)

    col_w = 560
    gap = 80
    x_left = (W - 2 * col_w - gap) / 2
    x_right = x_left + col_w + gap

    _, _, y1, _, h1 = b.box(
        x_left,
        y,
        col_w,
        280,
        "Now — Phases 1–3\n\n"
        "• 8–16 pods × 16 concurrency\n"
        "• eval_global 256 · job 128\n"
        "• import 96 / workspace 48 (keep)\n"
        "• KEDA on org-wide pending rows\n"
        "• No PgBouncer\n\n"
        "~256 parallel rows at max scale\n"
        "Dual 10k ≈ 32 min",
        bg="#d0bfff",
        font_size=17,
    )
    _, _, y2, _, h2 = b.box(
        x_right,
        y,
        col_w,
        280,
        "Future — Phases 4–5\n\n"
        "• 16–20 pods × 28 concurrency\n"
        "• eval_global 560 · workspace 280\n"
        "• PgBouncer per catalog + shard\n"
        "• transaction pool mode\n"
        "• Small app pools (5–8)\n\n"
        "Dual 10k in ~30 min target",
        bg="#b2f2bb",
        font_size=17,
    )

    mid_y = y + max(h1, h2) / 2
    b.arrow_right(x_left + col_w + 4, x_right - 4, mid_y, label="PgBouncer")

    y = y + max(h1, h2) + 48
    return b.note(
        y,
        "PgBouncer multiplexes many client connections into fewer server connections to RDS.\n"
        "Required before scaling to 20 pods × 28 threads without pool_timeout errors.",
        bg=C_NOTE,
    )


SECTIONS: list[tuple[str, str, object]] = [
    ("01", "Platform Architecture", draw_platform_architecture),
    ("02", "Postgres ↔ Redis ↔ Workers", draw_postgres_redis_flow),
    ("03", "Call Import Pipeline", draw_call_import_pipeline),
    ("04", "Database Sharding", draw_sharding_topology),
    ("05", "Fair Dispatch & Inflight Limits", draw_fair_dispatch),
    ("06", "Scaling Roadmap (KEDA + PgBouncer)", draw_keda_pgbouncer_roadmap),
]


def build_combined() -> None:
    b = ExcalidrawBuilder(canvas_width=W)
    y = b.title("EfficientAI Call Import — Architecture Diagrams")
    y = b.subtitle("All 6 diagrams in one canvas — scroll down to navigate sections 01–06", y)
    y += 48

    for number, title, draw_fn in SECTIONS:
        y = b.section_header(y, title, number=number)
        y = draw_fn(b, y)
        y += SECTION_GAP

    b.save(COMBINED, fit_viewport=False, zoom=0.75)


def main() -> None:
    build_combined()

    # Remove legacy per-diagram files if present
    for legacy in OUT.glob("0*.excalidraw"):
        legacy.unlink()
        print(f"Removed legacy file: {legacy.name}")

    print(f"Wrote combined diagram: {COMBINED}")


if __name__ == "__main__":
    main()
