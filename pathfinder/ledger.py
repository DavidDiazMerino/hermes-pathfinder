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
CREATE TABLE IF NOT EXISTS labs (
    lab_id       TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    created_at   REAL NOT NULL,
    passed       INTEGER NOT NULL,
    counts_json  TEXT NOT NULL,
    results_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources_read (
    source_id  TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    tier       TEXT NOT NULL,
    title      TEXT,
    sha256     TEXT NOT NULL,
    chars      INTEGER NOT NULL,
    tool       TEXT NOT NULL,
    read_at    REAL NOT NULL
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

    # ------------------------------------------------------------ labs
    def record_lab(self, run_id: str, outcome: dict[str, Any]) -> str:
        n = self.conn.execute("SELECT COUNT(*) FROM labs WHERE run_id = ?", (run_id,)).fetchone()[0]
        lab_id = f"{run_id}/lab{n + 1}"
        self.conn.execute(
            "INSERT INTO labs VALUES (?,?,?,?,?,?)",
            (lab_id, run_id, time.time(), 1 if outcome["passed"] else 0,
             json.dumps(outcome["counts"]), json.dumps(outcome["results"])),
        )
        self.conn.commit()
        return lab_id

    def latest_lab(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT lab_id, created_at, passed, counts_json FROM labs WHERE run_id = ? "
            "ORDER BY created_at DESC, lab_id DESC LIMIT 1", (run_id,)).fetchone()
        if row is None:
            return None
        return {"lab_id": row[0], "created_at": row[1], "passed": bool(row[2]), "counts": json.loads(row[3])}

    def evidence_status(self, run_id: str) -> dict[str, Any]:
        """What a run can back: 'verified' only when its latest lab passed and checked at least one claim."""
        if run_id.startswith("src-"):
            src = self.get_source(run_id)
            if src is None:
                return {"run_id": run_id, "status": "unknown", "reason": "no such source record in the Pathfinder ledger"}
            if src["tier"] in ("official", "standard"):
                return {"run_id": run_id, "status": "documented", "kind": "source", "tier": src["tier"],
                        "url": src["url"], "family": None, "created_at": src["read_at"]}
            return {"run_id": run_id, "status": "weak-source", "kind": "source", "tier": src["tier"],
                    "reason": f"{src['tier']} source; corroborate with an official one", "url": src["url"],
                    "family": None, "created_at": src["read_at"]}
        run = self.get_run(run_id)
        if run is None:
            return {"run_id": run_id, "status": "unknown", "reason": "no such run in the Pathfinder ledger"}
        lab = self.latest_lab(run_id)
        if lab is None:
            return {"run_id": run_id, "status": "inspected", "reason": "contract parsed, no lab run yet",
                    "family": run["family"], "created_at": run["created_at"]}
        if not lab["passed"]:
            return {"run_id": run_id, "status": "failed", "reason": f"latest lab {lab['lab_id']} has failures",
                    "family": run["family"], "created_at": lab["created_at"]}
        if lab["counts"].get("claims", 0) == 0:
            return {"run_id": run_id, "status": "inspected",
                    "reason": "lab passed integrity checks but tested no claims", "family": run["family"],
                    "created_at": lab["created_at"]}
        return {"run_id": run_id, "status": "verified", "lab_id": lab["lab_id"], "family": run["family"],
                "created_at": lab["created_at"]}

    # ------------------------------------------------------------ sources read
    def record_source(self, *, url: str, tier: str, title: str | None, content: str, tool: str) -> str:
        """Record that a page was read; the same URL with the same content keeps its id."""
        import hashlib
        sha = hashlib.sha256((content or "").encode("utf-8", "replace")).hexdigest()
        row = self.conn.execute("SELECT source_id FROM sources_read WHERE url = ? AND sha256 = ?",
                                (url, sha)).fetchone()
        if row:
            return row[0]
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        base = f"src-{stamp}-{sha[:6]}"
        source_id, n = base, 1
        while self.conn.execute("SELECT 1 FROM sources_read WHERE source_id = ?", (source_id,)).fetchone():
            n += 1
            source_id = f"{base}-{n}"
        self.conn.execute("INSERT INTO sources_read VALUES (?,?,?,?,?,?,?,?)",
                          (source_id, url, tier, title, sha, len(content or ""), tool, time.time()))
        self.conn.commit()
        return source_id

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM sources_read WHERE source_id = ?", (source_id,))
        row = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], row)) if row else None

    def recent_sources(self, limit: int = 10) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT source_id, tier, url, read_at FROM sources_read ORDER BY read_at DESC LIMIT ?",
                                (limit,))
        return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]

    # ------------------------------------------------------------ skills
    def link_skill(self, skill_name: str, run_ids: list[str], action: str) -> None:
        now = time.time()
        self.conn.executemany("INSERT INTO skill_links VALUES (?,?,?,?)",
                              [(skill_name, r, action, now) for r in run_ids])
        self.conn.commit()

    def skill_links(self, skill_name: str) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT run_id, action, created_at FROM skill_links WHERE skill_name = ? ORDER BY created_at",
            (skill_name,))
        return [{"run_id": r[0], "action": r[1], "created_at": r[2]} for r in cur.fetchall()]

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT run_id, created_at, kind, domain, source_ref, family FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def linked_skills(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for name, run_id in self.conn.execute(
                "SELECT skill_name, run_id FROM skill_links ORDER BY created_at"):
            out.setdefault(name, [])
            if run_id not in out[name]:
                out[name].append(run_id)
        return out
