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

from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"


class AgentUnavailable(RuntimeError):
    pass


def load_prompt(name: str, **subs: str) -> str:
    text = (PROMPTS / f"{name}.md").read_text()
    for k, v in subs.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def run_agent(prompt: str, cwd: Path, allowed_tools: list[str],
              system_prompt: str | None = None, max_turns: int = 40) -> dict:
    """Run one agent session, working directory = the run's artifacts dir.
    Returns {"result", "cost_usd", "num_turns"} — the artifacts on disk are
    what matter; the cost feeds the budget odometer."""
    try:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError as e:  # pragma: no cover
        raise AgentUnavailable(f"claude-agent-sdk not installed: {e}") from e

    # Headless agents cannot answer permission prompts, so the mode is
    # bypassPermissions and the real constraint is the per-stage tool
    # allowlist (no Bash anywhere; S0/S3/S4 get Read/Write only).
    options = ClaudeAgentOptions(
        cwd=str(cwd),
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        system_prompt=system_prompt,
        max_turns=max_turns,
    )

    async def _run() -> dict:
        out: dict = {"result": "", "cost_usd": None, "num_turns": None}
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                out["result"] = message.result or ""
                out["cost_usd"] = getattr(message, "total_cost_usd", None)
                out["num_turns"] = getattr(message, "num_turns", None)
        return out

    return anyio.run(_run)
