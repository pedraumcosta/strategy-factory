"""Typed decision points — the Plan §17 topic 2 spike.

ONE decision behind an interface: graveyard kinship at S0 ("is this card
the same family as a recorded corpse?"), asked as an atomic typed question
and answered by interchangeable backends — the pinned stage LLM, a
deliberately cheap LLM (the honest comparator: the payoff of any swap is
bounded by the cheapest generator that could already do the job), and
TypeSafe's Jev decision model. Code owns the thresholds and the criteria;
the backends only answer the question (the reading's "atomic questions,
composed in code").

The spike's discipline (same as TimeGPT's): the model version is pinned
and logged per response, costs land on the ledger, and no backend's
confidence is trusted until its probabilities verify as calibrated on OUR
labeled set (fixtures/kinship_eval.json) — reliability, Brier, ECE. All
three backends report confidence by the same formula (Jev's published
one), so the numbers are comparable.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.14.0"            # pinned; the response's model is logged
JEV_USD_PER_MTOK = 0.042            # input tokens only; output is free

NOVEL_DESC = ("The same family as NO recorded corpse: the mechanism, not "
              "merely the parameters or the wording, differs from every "
              "closed idea-space listed.")

INSTRUCTIONS = (
    "A strategy factory records every killed hypothesis family ('corpse') "
    "and refuses to re-enter a closed idea-space: nearby lookbacks, other "
    "parameter values, and re-worded premises of a dead mechanism are the "
    "SAME family. Judge which recorded family this new hypothesis card "
    "belongs to, or 'novel' if its mechanism is genuinely outside every "
    "closed space. Judge the mechanism (what is ranked or timed, and why "
    "it would pay), not the vocabulary.")


class DecisionUnavailable(RuntimeError):
    pass


@dataclass
class Verdict:
    choice: str
    probabilities: dict[str, float]
    confidence: float
    model: str
    latency_s: float
    cost_usd: float


def kinship_criteria(families: dict) -> dict[str, str]:
    crit = {k: v["description"] for k, v in families.items()
            if not k.startswith("_")}
    crit["novel"] = NOVEL_DESC
    return crit


def card_state(card: dict) -> str:
    """The card fields a kinship judgment needs — nothing else leaves."""
    keep = {k: card[k] for k in
            ("name", "premise", "edge_source", "cross_sectional")
            if k in card}
    expr = card.get("factor_expr") or (card.get("factor") or {}).get("expr")
    if expr:
        keep["factor_expr"] = expr
    return json.dumps(keep, sort_keys=True)


def choice_confidence(probabilities: dict[str, float]) -> float:
    """Jev's published confidence formula for choice questions —
    (p_max - 1/n) / (1 - 1/n) — applied to every backend so the
    reliability numbers are comparable."""
    n = len(probabilities)
    if n < 2:
        return 0.0
    p_max = max(probabilities.values())
    return max(0.0, (p_max - 1 / n) / (1 - 1 / n))


# --- backend: Jev ---------------------------------------------------------------

def _http_post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def jev_kinship(card: dict, families: dict, model: str = JEV_MODEL,
                _post=None) -> Verdict:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise DecisionUnavailable(
            "TYPESAFE_API_KEY is not set. Create a key at "
            "https://console.typesafe.ai/keys (self-serve) and export it "
            "before running the jev backend.")
    body = {"state": card_state(card), "model": model,
            "questions": {"kinship": {"type": "choice",
                                      "instructions": INSTRUCTIONS,
                                      "criteria": kinship_criteria(families)}}}
    post = _post or _http_post
    t0 = time.perf_counter()
    resp = post(JEV_URL, body, {"Authorization": f"Bearer {key}"})
    latency = time.perf_counter() - t0
    ans = resp["answers"]["kinship"]
    return Verdict(choice=ans["choice"],
                   probabilities=dict(ans["probabilities"]),
                   confidence=float(ans["confidence"]),
                   model=resp["model"], latency_s=round(latency, 3),
                   cost_usd=resp["usage"]["input_tokens"] * JEV_USD_PER_MTOK / 1e6)


# --- backend: Claude (the stage model, and the cheap comparator) ----------------

def _agent_oneshot(prompt: str, model: str) -> tuple[str, float, float]:
    """One no-tools agent turn; returns (text, cost_usd, latency_s)."""
    import anyio
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(allowed_tools=[], max_turns=1, model=model,
                                 permission_mode="bypassPermissions")

    async def _run():
        text, cost = "", 0.0
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                text = message.result or ""
                cost = getattr(message, "total_cost_usd", None) or 0.0
        return text, cost

    t0 = time.perf_counter()
    text, cost = anyio.run(_run)
    return text, cost, time.perf_counter() - t0


def _parse_choice_json(text: str, options: list[str]) -> tuple[str, dict]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in answer: {text[:200]!r}")
    obj = json.loads(m.group(0))
    probs = {k: max(0.0, float(obj.get("probabilities", {}).get(k, 0.0)))
             for k in options}
    total = sum(probs.values())
    probs = ({k: v / total for k, v in probs.items()} if total > 0
             else {k: 1 / len(options) for k in options})
    choice = obj.get("choice")
    if choice not in options:
        choice = max(probs, key=probs.get)
    return choice, probs


def claude_kinship(card: dict, families: dict, model: str,
                   _run=None) -> Verdict:
    criteria = kinship_criteria(families)
    options = list(criteria)
    prompt = (
        f"{INSTRUCTIONS}\n\nThe recorded families (option key: scope):\n"
        + "\n".join(f"- {k}: {d}" for k, d in criteria.items())
        + f"\n\nThe new hypothesis card:\n{card_state(card)}\n\n"
        + "Answer ONLY with a JSON object, no prose, of the form "
        + '{"choice": "<option key>", "probabilities": {"<option key>": p, ...}} '
        + "covering every option key with probabilities summing to 1.")
    run = _run or _agent_oneshot
    text, cost, latency = run(prompt, model)
    choice, probs = _parse_choice_json(text, options)
    return Verdict(choice=choice, probabilities=probs,
                   confidence=choice_confidence(probs), model=model,
                   latency_s=round(latency, 3), cost_usd=cost)


# --- the calibration arithmetic (our labeled set, not their distribution) -------

def brier(results: list[tuple[Verdict, str]]) -> float:
    """Mean multiclass Brier score: sum_k (p_k - 1[k==label])^2 per case."""
    tot = 0.0
    for v, label in results:
        tot += sum((p - (1.0 if k == label else 0.0)) ** 2
                   for k, p in v.probabilities.items())
    return tot / len(results)


def ece(results: list[tuple[Verdict, str]], bins: int = 5) -> float:
    """Expected calibration error on the confidence of the chosen option:
    |empirical accuracy - mean confidence| weighted by bin occupancy."""
    binned: dict[int, list[tuple[float, bool]]] = {}
    for v, label in results:
        b = min(int(v.confidence * bins), bins - 1)
        binned.setdefault(b, []).append((v.confidence, v.choice == label))
    n = len(results)
    err = 0.0
    for rows in binned.values():
        conf = sum(c for c, _ in rows) / len(rows)
        acc = sum(ok for _, ok in rows) / len(rows)
        err += len(rows) / n * abs(acc - conf)
    return err
