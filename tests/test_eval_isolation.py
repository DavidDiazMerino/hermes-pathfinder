import json
import os
import sys
from types import SimpleNamespace

import pytest

from eval import isolation, run_eval, run_traps


def tool_use(name, **arguments):
    return json.dumps({"type": "tool_use", "name": name, "input": arguments})


def test_detects_reads_outside_workspace(tmp_path):
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    workspace = repo / "eval" / "runs" / "mine"
    workspace.mkdir(parents=True)
    answer_key = repo / "eval" / "traps.py"
    fixture = workspace / "service_metadata.xml"
    roots = [str(repo)]

    assert isolation.contaminated(tool_use("read_file", path=str(answer_key)), str(workspace), roots) == [
        str(answer_key)
    ]
    assert isolation.contaminated(tool_use("read_file", path=str(fixture)), str(workspace), roots) == []
    assert isolation.contaminated(tool_use("pathfinder_inspect", path=str(answer_key)), str(workspace), roots) == []
    assert isolation.contaminated(tool_use("read_file", path=str(repo.with_name(repo.name + "-other"))),
                                  str(workspace), roots) == []

    alias = tmp_path / "plugin"
    alias.symlink_to(repo, target_is_directory=True)
    relative_key = repo / "eval" / "expected.json"
    ignored = repo / "docs" / "scenarios.md"
    transcript = "\n".join([
        tool_use("terminal", command=f'cat "{alias}/eval/traps.py"'),
        tool_use("read_file", path=os.path.relpath(relative_key, workspace)),
        tool_use("web_search", query=str(ignored)),
        tool_use("skill_view", path=str(ignored)),
        json.dumps({"type": "tool_result", "name": "read_file", "output": str(ignored)}),
    ])
    assert isolation.contaminated(transcript, str(workspace), roots) == [str(relative_key), str(answer_key)]


@pytest.mark.parametrize("runner", [run_eval, run_traps])
def test_summary_excludes_contaminated_rows(runner):
    clean = {"model": "model", "condition": "A", "contract": "fixture", "tokens": 10, "wall_s": 1,
             "ratio": 0.5, "points": 1, "total": 2, "parsed": True, "used_pathfinder": False,
             "correct": False, "checks_passed": 1, "checks_total": 2, "cites_official": False,
             "cost_usd": 0.1}
    flagged = {"model": "model", "condition": "A", "contract": "fixture",
               "contaminated": ["/repo/eval/traps.py"]}
    infra = {"model": "model", "condition": "A", "contract": "fixture", "infra_error": True}
    summary = runner.summarise([clean, flagged, infra, {**flagged, "condition": "C"}])
    assert [(r["condition"], r["runs"], r["excluded_contaminated"]) for r in summary] == [
        ("A", 1, 1), ("C", 0, 1)
    ]
    if runner is run_eval:
        assert summary[0]["score_mean"] == 0.5
    else:
        assert summary[0]["checks"] == "1/2"


def test_default_work_dir_is_outside_repo(tmp_path):
    repo = run_eval.ROOT
    assert not isolation.round_workspace(repo, str(isolation.default_work_dir()), "stamp").is_relative_to(repo)
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    for invalid in (repo, repo / "eval" / "runs", alias):
        with pytest.raises(ValueError, match="outside the repository"):
            isolation.round_workspace(repo, str(invalid), "stamp")


@pytest.mark.parametrize(("runner", "selection"), [
    (run_eval, ["--contracts", "large_v4"]),
    (run_traps, ["--traps", "aufk-public"]),
])
def test_runner_archives_session_and_reports_contamination(tmp_path, monkeypatch, runner, selection):
    repo = tmp_path / "repo"
    (repo / "eval").mkdir(parents=True)
    work = tmp_path / "work"
    answer_key = repo / "eval" / "traps.py"
    transcript = "\n".join([
        tool_use("read_file", path=str(answer_key)),
        json.dumps({"type": "result", "text": "test answer", "tokens": {"total": 10}}),
    ])

    def fake_hermes(cmd, *, cwd, **kwargs):
        assert cmd[0] == "hermes"
        assert cmd[cmd.index("--in") + 1] == str(cwd)
        assert cwd.is_relative_to(work)
        expected_files = ["service_metadata.xml"] if runner is run_eval else []
        assert sorted(p.name for p in cwd.iterdir()) == expected_files
        return SimpleNamespace(stdout=transcript, returncode=0)

    monkeypatch.setattr(runner, "ROOT", repo)
    monkeypatch.setattr(runner, "load_pricing", lambda: {})
    monkeypatch.setattr(runner.subprocess, "run", fake_hermes)
    monkeypatch.setattr(sys, "argv", ["runner", "--work-dir", str(work), "--runs", "1", "--conditions", "A", *selection])
    if runner is run_eval:
        monkeypatch.setattr(run_eval, "CONTRACTS", run_eval.CONTRACTS.copy())
        monkeypatch.setattr(run_eval, "GENERATED", {})
    runner.main()

    if runner is run_eval:
        assert list((repo / "eval" / "runs").rglob("large_v4.expected.json"))
        assert not list(work.rglob("large_v4.expected.json"))
    (archived,) = (repo / "eval" / "runs").rglob("transcript.jsonl")
    assert archived.read_text() == transcript
    assert archived.with_name("answer.md").read_text() == "test answer"
    (result,) = (repo / "eval" / "results").glob("*.json")
    report = json.loads(result.read_text())
    assert report["runs"][0]["contaminated"] == [str(answer_key)]
    assert report["summary"][0]["excluded_contaminated"] == 1
