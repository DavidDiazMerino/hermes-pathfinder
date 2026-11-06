"""Enterprise Pathfinder: a Hermes plugin that gives the agent a map, a contract inspector and an
evidence ledger for enterprise software domains (first pack: SAP)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

PLUGIN_NAME = "enterprise-pathfinder"
_ROOT = Path(__file__).resolve().parent


def register(ctx):
    # Imports stay inside register() so the core package can be tested without Hermes.
    from .pathfinder import schemas, tools
    from .pathfinder.ledger import Ledger

    ledger_holder: dict[str, Ledger] = {}

    def get_ledger() -> Ledger:
        # Resolved lazily: the data dir follows the active profile.
        from plugins.plugin_storage import plugin_data_dir, plugin_db
        data_dir = plugin_data_dir(PLUGIN_NAME)
        key = str(data_dir)
        if key not in ledger_holder:
            ledger_holder[key] = Ledger(plugin_db(PLUGIN_NAME, "ledger.db"), data_dir)
        return ledger_holder[key]

    def get_cwd() -> str:
        try:
            cwd = ctx.session_cwd()
            if cwd:
                return cwd
        except Exception:
            pass
        try:
            from agent.runtime_cwd import resolve_agent_cwd
            return str(resolve_agent_cwd())
        except Exception:
            return os.getcwd()

    rt = tools.Runtime(ledger=get_ledger, cwd=get_cwd)

    ctx.register_tool(name="pathfinder_sources", toolset="pathfinder", schema=schemas.SOURCES,
                      handler=lambda args, **kw: tools.sources(args or {}, rt), emoji="🧭")
    ctx.register_tool(name="pathfinder_inspect", toolset="pathfinder", schema=schemas.INSPECT,
                      handler=lambda args, **kw: tools.inspect(args or {}, rt), emoji="🔎")

    skills_dir = _ROOT / "skills"
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            ctx.register_skill(child.name, child / "SKILL.md")

    def handle_pathfinder(raw_args: str, *, session_key: str = "", **kwargs) -> str:
        text = (raw_args or "").strip()
        if not text or text in {"help", "-h", "--help"}:
            return ("Usage:\n"
                    "  /pathfinder <task>     start a Pathfinder mission (SAP pack) for this task\n"
                    "  /pathfinder status     show recent evidence runs")
        if text == "status":
            try:
                runs = get_ledger().recent_runs(10)
            except Exception as exc:
                return f"Pathfinder ledger unavailable: {exc}"
            if not runs:
                return "No Pathfinder runs yet."
            return "Recent Pathfinder runs:\n" + "\n".join(
                f"  {r['run_id']}  {r['kind']:<8} {r['family'] or '':<3} {r['source_ref']}" for r in runs)
        mission = (
            f"Pathfinder mission: {text}\n\n"
            f"Load skill_view('{PLUGIN_NAME}:method') and follow it. Use pathfinder_sources to orient "
            "yourself before researching, and pathfinder_inspect for any fact about a contract. "
            "Cite run_ids for claims about contracts."
        )
        try:
            if ctx.inject_message(mission, session_key=session_key or None):
                return "Pathfinder mission started."
        except Exception as exc:
            logger.warning("pathfinder: inject_message failed: %s", exc)
        return "Could not start the mission automatically. Paste this as your next message:\n\n" + mission

    ctx.register_command("pathfinder", handler=handle_pathfinder,
                         description="Start a Pathfinder mission or show evidence runs",
                         args_hint="<task> | status")
