"""Durable dispatch reservations and completed evaluation records."""

import json
import os
from pathlib import Path


def write_record(path: Path, row: dict, *, reserve: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if reserve else "a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


def load_records(run_dir: Path) -> list[dict]:
    path = run_dir / "records.jsonl"
    rows = (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if path.exists()
        else []
    )
    completed = {row["request_id"] for row in rows}
    # A reservation without a completed record consumed budget but has no known outcome.
    # Invalid/truncated files fail closed rather than silently allowing another dispatch.
    for path in sorted((run_dir / "dispatches").glob("*.json")):
        reservation = json.loads(path.read_text(encoding="utf-8"))
        if reservation["request_id"] not in completed:
            rows.append(reservation)
    return rows
