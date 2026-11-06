"""Thin wrapper over the Claude Agent SDK for the LLM stages (S0/S1/S3/S4).

Design rule (Plan §1.5 / DESIGN §1): LLM judgment lives INSIDE a stage; the
orchestrator and the validators are deterministic. Every stage here follows
the same shape — the agent is asked to WRITE ARTIFACT FILES into the run's
artifacts/ directory, and the stage function then validates those files
deterministically. The agent's chat output is kept only as a log.

Stages accept an injectable `agent_fn` so tests run without tokens; the
default implementation shells into the Claude Agent SDK. Every real agent
call is appended to the trial ledger's `llm` kind — the $100/month budget
odometer counts these too (Plan §11f).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"

# Pinned stage model (Plan §17 topic 2's first lesson, applied to ourselves:
# a confidence or behavior calibrated on one model breaks quietly when the
# version drifts underneath it). Before this pin the stages ran on whatever
# the CLI defaulted to — unnamed and unlogged.
MODEL = os.environ.get("FACTORY_LLM_MODEL", "claude-opus-5-5")


class AgentUnavailable(RuntimeError):
    pass


# --- the read guard -----------------------------------------------------------
# Measured hole (Plan §17 topic 3): an S1 agent once Read its own 993k-char
# session transcript out of ~/.claude/projects — one tool call, ~250k tokens,
# ~5% of lifetime stage spend. Nothing scoped what stage agents may read, so
# this guard does, deterministically, before the tool runs.

def forbidden_read(tool_input: dict) -> str | None:
    """Why a path-bearing tool call must not run, or None if it may.
    Blocks: anything under ~/.claude (transcripts, configs, credentials),
    any .jsonl (ledgers and transcripts are not research material), and
    key files (.env*)."""
    claude_dir = os.path.realpath(os.path.expanduser("~/.claude"))
    for key in ("file_path", "path"):
        p = tool_input.get(key)
        if not p:
            continue
        rp = os.path.realpath(os.path.expanduser(str(p)))
        if rp == claude_dir or rp.startswith(claude_dir + os.sep):
            return (f"{key} is under ~/.claude — session transcripts and "
                    "credentials are not stage inputs")
        base = os.path.basename(rp)
        if base.endswith(".jsonl"):
            return "ledger/transcript .jsonl files are not stage inputs"
        if base.startswith(".env"):
            return "key files are not stage inputs"
    return None


async def _read_guard(input_data, tool_use_id, context) -> dict:
    reason = forbidden_read((input_data or {}).get("tool_input") or {})
    if reason:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}
    return {}


def load_prompt(name: str, **subs: str) -> str:
    text = (PROMPTS / f"{name}.md").read_text()
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def run_agent(prompt: str, cwd: Path, allowed_tools: list[str],
              system_prompt: str | None = None, max_turns: int = 40) -> dict:
    """Run one agent session, working directory = the run's artifacts dir.
    Returns {"result", "cost_usd", "num_turns", "model", "duration_s"} — the
    artifacts on disk are what matter; the cost, model and latency feed the
    budget odometer."""
    try:
        import anyio
        from claude_agent_sdk import (ClaudeAgentOptions, HookMatcher,
                                      ResultMessage, query)
    except ImportError as e:  # pragma: no cover
        raise AgentUnavailable(f"claude-agent-sdk not installed: {e}") from e

    # Headless agents cannot answer permission prompts, so the mode is
    # bypassPermissions and the real constraints are the per-stage tool
    # allowlist (no Bash anywhere; S0/S3/S4 get Read/Write only) and the
    # read guard hook — hooks run regardless of permission mode.
    options = ClaudeAgentOptions(
        cwd=str(cwd),
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        system_prompt=system_prompt,
        max_turns=max_turns,
        model=MODEL,
        hooks={"PreToolUse": [HookMatcher(matcher="Read|Glob|Grep",
                                          hooks=[_read_guard])]},
    )

    async def _run() -> dict:
        out: dict = {"result": "", "cost_usd": None, "num_turns": None,
                     "model": MODEL, "duration_s": None}
        t0 = time.perf_counter()
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                out["result"] = message.result or ""
                out["cost_usd"] = getattr(message, "total_cost_usd", None)
                out["num_turns"] = getattr(message, "num_turns", None)
        out["duration_s"] = round(time.perf_counter() - t0, 2)
        return out

    return anyio.run(_run)
