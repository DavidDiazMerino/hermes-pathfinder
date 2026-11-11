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
    ctx.register_tool(name="pathfinder_lab", toolset="pathfinder", schema=schemas.LAB,
                      handler=lambda args, **kw: tools.lab(args or {}, rt), emoji="🧪")

    def read_handler(args, **kw):
        from plugins.plugin_storage import plugin_data_dir
        from .pathfinder import packs as _packs
        rules = [r for d in _packs.available() for r in _packs.load(d).get("trust_map", {}).get("rules", [])]
        enabled = str(ctx.get_config("network", default="official-only") or "official-only") != "off"
        return tools.read_document(args or {}, rt, trust_map={"rules": rules},
                                   cache_dir=plugin_data_dir(PLUGIN_NAME) / "cache", enabled=enabled)

    ctx.register_tool(name="pathfinder_read", toolset="pathfinder", schema=schemas.READ,
                      handler=read_handler, emoji="📄")

    skills_dir = _ROOT / "skills"
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            ctx.register_skill(child.name, child / "SKILL.md")

    # ------------------------------------------------------------ evidence gate
    from .pathfinder import gate, packs

    def gate_settings() -> tuple[str, list[str]]:
        mode = str(ctx.get_config("gate_mode", default="strict") or "strict").lower()
        if mode not in gate.MODES:
            mode = "strict"
        keywords: list[str] = []
        for domain in packs.available():
            keywords += packs.load(domain).get("gate_keywords", [])
        return mode, keywords

    def guard_paths() -> tuple[str, list[str]]:
        from plugins.plugin_storage import plugin_data_dir
        data_dir = plugin_data_dir(PLUGIN_NAME)
        hermes_home = data_dir.parent.parent  # <HERMES_HOME>/plugin-data/<name>
        return str(data_dir), [str(hermes_home / "skills")]

    def on_pre_tool_call(tool_name: str = "", args: dict | None = None, **kwargs):
        if tool_name != "skill_manage":
            try:
                mode, keywords = gate_settings()
                data_dir, roots = guard_paths()
                message = gate.guard_other_tool(tool_name, args or {}, get_ledger(), data_dir=data_dir,
                                                skills_roots=roots, mode=mode, keywords=keywords)
            except Exception as exc:
                logger.warning("pathfinder guard error: %s", exc, exc_info=True)
                return None  # never break unrelated tools because of our own failure
            return {"action": "block", "message": message} if message else None
        try:
            mode, keywords = gate_settings()
            decision = gate.evaluate(args or {}, get_ledger(), mode=mode, keywords=keywords)
        except Exception as exc:
            # Fail closed for domain writes we cannot evaluate; say why.
            logger.warning("pathfinder gate error: %s", exc, exc_info=True)
            return {"action": "block", "message": f"Pathfinder evidence gate could not evaluate this write: {exc}"}
        if not decision["allow"]:
            return {"action": "block", "message": decision["message"]}
        return None

    def on_post_tool_call(tool_name: str = "", args: dict | None = None, result: str = "", **kwargs):
        if tool_name != "skill_manage":
            return
        try:
            import json as _json
            payload = _json.loads(result) if isinstance(result, str) else (result or {})
            if not isinstance(payload, dict) or not payload.get("success"):
                return
            mode, keywords = gate_settings()
            ledger = get_ledger()
            decision = gate.evaluate(args or {}, ledger, mode=mode, keywords=keywords)
            if not decision["domain_skills"] or not decision["verified"]:
                return
            action = "staged" if payload.get("staged") else "applied"
            for name in decision["domain_skills"]:
                ledger.link_skill(name, decision["verified"], action)
        except Exception as exc:
            logger.warning("pathfinder: could not record skill evidence: %s", exc)

    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)

    # ------------------------------------------------------------ live source trust
    from .pathfinder import webtrust

    def trust_settings():
        trust_maps, keywords = [], []
        for domain in packs.available():
            pack = packs.load(domain)
            if pack.get("trust_map"):
                trust_maps.append(pack["trust_map"])
            keywords += pack.get("relevance_keywords", pack.get("gate_keywords", []))
        merged = {"rules": [r for tm in trust_maps for r in tm.get("rules", [])]}
        return merged, gate.keyword_regex(keywords)

    def on_transform_tool_result(tool_name: str = "", args: dict | None = None, result=None, **kwargs):
        if tool_name not in webtrust.SEARCH_TOOLS | webtrust.READ_TOOLS:
            return None
        if not ctx.get_config("source_tagging", default=True):
            return None
        try:
            trust_map, kw_re = trust_settings()
            return webtrust.annotate(tool_name, args or {}, result, trust_map=trust_map,
                                     ledger=get_ledger(), kw_re=kw_re)
        except Exception as exc:
            logger.warning("pathfinder: source tagging failed: %s", exc)
            return None

    ctx.register_hook("transform_tool_result", on_transform_tool_result)

    # ------------------------------------------------------------ /pathfinder
    def status_text() -> str:
        ledger = get_ledger()
        runs = ledger.recent_runs(10)
        if not runs:
            return "No Pathfinder runs yet."
        lines = ["Recent Pathfinder runs:"]
        for r in runs:
            st = ledger.evidence_status(r["run_id"])
            lines.append(f"  {r['run_id']}  {st['status']:<9} {r['family'] or '':<3} {r['source_ref']}")
        skills = ledger.linked_skills()
        if skills:
            lines.append("Skills backed by evidence:")
            for name, run_ids in skills.items():
                lines.append(f"  {name}: {', '.join(run_ids)}")
        sources = ledger.recent_sources(5)
        if sources:
            lines.append("Recent sources read:")
            for src in sources:
                lines.append(f"  {src['source_id']}  {src['tier']:<12} {src['url'][:90]}")
        mode, _ = gate_settings()
        lines.append(f"Evidence gate: {mode}")
        return "\n".join(lines)

    def handle_pathfinder(raw_args: str, *, session_key: str = "", **kwargs) -> str:
        text = (raw_args or "").strip()
        if not text or text in {"help", "-h", "--help"}:
            return ("Usage:\n"
                    "  /pathfinder <task>     start a Pathfinder mission (SAP pack) for this task\n"
                    "  /pathfinder status     show evidence runs, their status and the skills they back")
        if text == "status":
            try:
                return status_text()
            except Exception as exc:
                return f"Pathfinder ledger unavailable: {exc}"
        mission = (
            f"Pathfinder mission: {text}\n\n"
            f"Load skill_view('{PLUGIN_NAME}:method') and follow it. Start with "
            "pathfinder_sources(question=...). For documentation facts read the official source (web_extract, "
            "or pathfinder_read for large files) and cite its source_id. For facts about a contract use "
            "pathfinder_inspect and test your claims with pathfinder_lab, citing the run_id."
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
