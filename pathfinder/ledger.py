"""Evidence ledger: every inspection / lab run, stored in the plugin's own SQLite DB.

Kept free of Hermes imports so it can be unit-tested with any sqlite3 connection.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    kind          TEXT NOT NULL,          -- inspect | lab
    domain        TEXT NOT NULL,
    product       TEXT,
    source_kind   TEXT NOT NULL,          -- fixture | local_file
    source_ref    TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    family        TEXT,
    odata_version TEXT,
    summary_json  TEXT NOT NULL,
    contract_file TEXT
);
CREATE TABLE IF NOT EXISTS checks (
    run_id     TEXT NOT NULL,
    check_id   TEXT NOT NULL,
    status     TEXT NOT NULL,             -- passed | failed | skipped
    detail     TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, check_id)
);
CREATE TABLE IF NOT EXISTS skill_links (
    skill_name TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    action     TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class Ledger:
    def __init__(self, conn: sqlite3.Connection, data_dir: Path):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def new_run_id(self, sha256: str) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        base = f"pf-{stamp}-{sha256[:6]}"
        run_id, n = base, 1
        while self.get_run(run_id) is not None:
            n += 1
            run_id = f"{base}-{n}"
        return run_id

    def record_inspection(self, *, domain: str, product: str | None, source_kind: str, source_ref: str,
                          contract: dict[str, Any]) -> str:
        sha = contract["source"]["sha256"]
        run_id = self.new_run_id(sha)
        contracts_dir = self.data_dir / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        contract_file = contracts_dir / f"{run_id}.json"
        contract_file.write_text(json.dumps(contract, indent=1, sort_keys=True), encoding="utf-8")
        self.conn.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, time.time(), "inspect", domain, product, source_kind, source_ref, sha,
             contract.get("family"), contract.get("odata_version"), json.dumps(contract.get("summary", {})),
             str(contract_file)),
        )
        self.conn.commit()
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0] for c in cur.description]
        run = dict(zip(cols, row))
        run["summary"] = json.loads(run.pop("summary_json"))
        return run

    def load_contract(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if run is None or not run.get("contract_file"):
            return None
        path = Path(run["contract_file"])
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT run_id, created_at, kind, domain, source_ref, family FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
