"""The kinship decision interface (Plan §17 topic 2): every backend answers
the same atomic question against the same criteria, nothing but the card's
kinship-relevant fields leaves the machine, verdicts parse into the same
typed shape, and the calibration arithmetic is checkable by hand. No test
touches a vendor or an LLM: backends take injectable transports."""

import json

import pytest

from factory import decisions as dec

FAMILIES = {
    "risk_adjusted_momentum": {"description": "momentum rankings, any lookback"},
    "lowvol_rank": {"description": "low-volatility level rankings"},
}
CARD = {"name": "SharpeMom", "premise": "winners keep winning",
        "edge_source": "momentum", "cross_sectional": True,
        "factor": {"expr": "ts_ret(close, 90)"},
        "estimates": {"gross_edge_per_trade": 0.004},   # must NOT be sent
        "parameters": {"lookback": 90}}


def test_criteria_always_include_novel():
    crit = dec.kinship_criteria(FAMILIES)
    assert set(crit) == {"risk_adjusted_momentum", "lowvol_rank", "novel"}


def test_card_state_sends_only_kinship_fields():
    state = json.loads(dec.card_state(CARD))
    assert set(state) == {"name", "premise", "edge_source",
                          "cross_sectional", "factor_expr"}
    assert state["factor_expr"] == "ts_ret(close, 90)"
    assert "estimates" not in dec.card_state(CARD)


def test_jev_backend_request_shape_and_parsing(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "tk-test")
    sent = {}

    def fake_post(url, body, headers):
        sent.update(url=url, body=body, headers=headers)
        return {"model": "jev-1.14.0",
                "answers": {"kinship": {"type": "choice",
                                        "choice": "risk_adjusted_momentum",
                                        "confidence": 0.91,
                                        "probabilities": {
                                            "risk_adjusted_momentum": 0.94,
                                            "lowvol_rank": 0.01,
                                            "novel": 0.05}}},
                "usage": {"input_tokens": 4000, "output_tokens": 0}}

    v = dec.jev_kinship(CARD, FAMILIES, _post=fake_post)
    q = sent["body"]["questions"]["kinship"]
    assert q["type"] == "choice" and "novel" in q["criteria"]
    assert sent["body"]["model"] == "jev-1.14.0"          # pinned version sent
    assert "Bearer tk-test" in sent["headers"]["Authorization"]
    assert v.choice == "risk_adjusted_momentum" and v.confidence == 0.91
    assert v.model == "jev-1.14.0"                        # answered version logged
    assert v.cost_usd == pytest.approx(4000 * 0.042 / 1e6)


def test_jev_refuses_cleanly_without_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(dec.DecisionUnavailable, match="TYPESAFE_API_KEY"):
        dec.jev_kinship(CARD, FAMILIES)


def test_claude_backend_parses_and_normalizes(monkeypatch):
    def fake_run(prompt, model):
        assert "novel" in prompt and "ts_ret(close, 90)" in prompt
        return ('Here: {"choice": "risk_adjusted_momentum", "probabilities": '
                '{"risk_adjusted_momentum": 0.8, "lowvol_rank": 0.1, '
                '"novel": 0.3}}', 0.01, 2.5)   # sums to 1.2 -> renormalized

    v = dec.claude_kinship(CARD, FAMILIES, model="claude-haiku-5-5",
                           _run=fake_run)
    assert v.choice == "risk_adjusted_momentum"
    assert sum(v.probabilities.values()) == pytest.approx(1.0)
    assert v.probabilities["risk_adjusted_momentum"] == pytest.approx(0.8 / 1.2)
    assert 0 < v.confidence < 1


def test_claude_backend_recovers_choice_from_probabilities():
    def fake_run(prompt, model):
        return ('{"choice": "not_an_option", "probabilities": '
                '{"lowvol_rank": 0.9, "risk_adjusted_momentum": 0.05, '
                '"novel": 0.05}}', 0.0, 1.0)

    v = dec.claude_kinship(CARD, FAMILIES, model="m", _run=fake_run)
    assert v.choice == "lowvol_rank"


def test_confidence_formula_matches_jev_definition():
    assert dec.choice_confidence({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}) == 0.0
    assert dec.choice_confidence({"a": 1.0, "b": 0.0, "c": 0.0}) == pytest.approx(1.0)


def test_brier_and_ece_by_hand():
    perfect = dec.Verdict("a", {"a": 1.0, "b": 0.0}, 1.0, "m", 0, 0)
    wrong = dec.Verdict("b", {"a": 0.0, "b": 1.0}, 1.0, "m", 0, 0)
    assert dec.brier([(perfect, "a")]) == 0.0
    assert dec.brier([(wrong, "a")]) == 2.0          # worst multiclass case
    # a fully confident backend that is right half the time: ECE = 0.5
    assert dec.ece([(perfect, "a"), (wrong, "a")]) == pytest.approx(0.5)


def test_eval_fixture_is_well_formed():
    import pathlib
    root = pathlib.Path(dec.__file__).resolve().parents[1]
    families = json.loads((root / "fixtures" / "kinship_families.json").read_text())
    cases = json.loads((root / "fixtures" / "kinship_eval.json").read_text())["cases"]
    options = {k for k in families if not k.startswith("_")} | {"novel"}
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    assert all(c["label"] in options for c in cases)
    kinds = {c["kind"] for c in cases}
    assert kinds == {"real", "near_miss", "reskin", "novel"}
    assert sum(c["label"] == "novel" for c in cases) >= 5   # the novel side exists


def test_kinship_advisory_swallows_missing_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert dec.kinship_advisory(CARD, FAMILIES) is None


def test_kinship_advisory_swallows_vendor_failure():
    def boom(card, families):
        raise OSError("vendor down")
    assert dec.kinship_advisory(CARD, FAMILIES, _ask=boom) is None


def test_kinship_advisory_passes_the_verdict_through():
    v = dec.Verdict("novel", {"novel": 1.0}, 1.0, "jev-1.14.0", 0.1, 0.0)
    assert dec.kinship_advisory(CARD, FAMILIES, _ask=lambda c, f: v) is v
