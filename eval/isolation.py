"""Workspace and transcript checks for both evaluation runners."""

from __future__ import annotations

import json
import shlex
import tempfile
from collections.abc import Iterator
from pathlib import Path


def default_work_dir() -> Path:
    return Path(tempfile.gettempdir()) / "pf-eval"


def round_workspace(root: Path, work_dir: str, stamp: str) -> Path:
    base = Path(work_dir).expanduser().resolve()
    workspace = (base / stamp).resolve()
    if base.is_relative_to(root.resolve()) or workspace.is_relative_to(root.resolve()):
        raise ValueError(f"Evaluation work directory must be outside the repository: {workspace}")
    return workspace


def evaluation_roots(root: Path) -> list[str]:
    hermes = Path.home() / ".hermes"
    plugin = "plugins/enterprise-pathfinder"
    installs = [hermes / plugin, *hermes.glob(f"profiles/*/{plugin}")]
    return sorted({str(path.resolve()) for path in [root, *installs]})


def _path_arguments(value: object, key: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for name, argument in value.items():
            yield from _path_arguments(argument, name)
    elif isinstance(value, list):
        for argument in value:
            yield from _path_arguments(argument, key)
    elif isinstance(value, str) and value:
        if key in {"path", "file_path", "cwd", "workdir"}:
            yield value
        else:
            # Also catch literal paths in shell commands and inline scripts.
            lexer = shlex.shlex(value, posix=True, punctuation_chars="();<>|&,")
            lexer.whitespace_split = True
            lexer.commenters = ""
            try:
                for token in lexer:
                    if not token.startswith(("/", "~/")) and "=" in token:
                        token = token.split("=", 1)[1]
                    if "/" in token or token in {".", ".."}:
                        yield token
            except ValueError:
                pass  # Incomplete quoting in tool input.


def contaminated(transcript_text: str, workspace: str, forbidden_roots: list[str]) -> list[str]:
    """Return forbidden paths referenced by ordinary tools outside this session's workspace."""
    ws = Path(workspace).resolve()
    roots = [Path(root).expanduser().resolve() for root in forbidden_roots]
    found: set[str] = set()
    for line in transcript_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "tool_use":
            continue
        name = str(event.get("name", ""))
        if name == "skill_view" or name.startswith(("pathfinder_", "web_")):
            continue
        for argument in _path_arguments(event.get("input")):
            try:
                path = (ws / Path(argument).expanduser()).resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if not path.is_relative_to(ws) and any(path.is_relative_to(root) for root in roots):
                found.add(str(path))
    return sorted(found)


def archive_session(directory: Path, transcript: str, answer: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "transcript.jsonl").write_text(transcript, encoding="utf-8")
    (directory / "answer.md").write_text(answer, encoding="utf-8")
