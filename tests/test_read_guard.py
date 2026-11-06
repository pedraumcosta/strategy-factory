"""The stage read guard (Plan §17 topic 3): a stage agent once read its own
993k-char session transcript out of ~/.claude — one call, ~5% of lifetime
stage spend. The guard is a pure function plus a PreToolUse hook; no test
touches the SDK runtime or a vendor."""

import os

import anyio

from factory.stages.llm import _read_guard, forbidden_read

HOME = os.path.expanduser("~")


def test_claude_dir_is_forbidden_everywhere():
    for p in (f"{HOME}/.claude/projects/x/session.jsonl",
              f"{HOME}/.claude/settings.json",
              f"{HOME}/.claude",
              # traversal must not slip past the prefix check
              f"{HOME}/.claude/../.claude/projects/y.jsonl"):
        assert forbidden_read({"file_path": p}), p
    # a Grep/Glob scoped INTO ~/.claude is refused via its path field
    assert forbidden_read({"path": f"{HOME}/.claude/projects"})


def test_jsonl_and_env_files_are_forbidden_anywhere():
    assert "jsonl" in forbidden_read({"file_path": "/repo/ledgers/trials.jsonl"})
    assert forbidden_read({"file_path": "/repo/.env"})
    assert forbidden_read({"file_path": "/repo/.env.local"})


def test_ordinary_research_reads_pass():
    for inp in ({"file_path": f"{HOME}/Library/some-reading.md"},
                {"file_path": "/repo/artifacts/hypothesis.json"},
                {"path": "/repo", "pattern": "momentum"},
                # a content regex mentioning .env is not a path
                {"path": "/repo/docs", "pattern": r"\.env"},
                {}):
        assert forbidden_read(inp) is None, inp
    # only a true .jsonl suffix counts as a ledger/transcript
    assert forbidden_read({"file_path": "/repo/notes.jsonl.md"}) is None


def test_hook_denies_with_reason_and_allows_silently():
    denied = anyio.run(
        _read_guard,
        {"tool_input": {"file_path": f"{HOME}/.claude/projects/t.jsonl"}},
        None, None)
    out = denied["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "transcripts" in out["permissionDecisionReason"]
    allowed = anyio.run(
        _read_guard, {"tool_input": {"file_path": "/repo/README.md"}},
        None, None)
    assert allowed == {}
    assert anyio.run(_read_guard, {}, None, None) == {}   # malformed input
