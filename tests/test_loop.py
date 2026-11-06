"""The agent loop end to end with scripted models: real files, real test runs."""

import pytest

from harness_lab import specs
from harness_lab.models import ScriptedModel, message, tool_call
from harness_lab.pipelines import run_agent, run_scenario
from harness_lab.scenarios import SCENARIOS


@pytest.mark.parametrize("key", list(SCENARIOS))
def test_every_scenario_reaches_its_expected_outcome(key):
    assert run_scenario(key).outcome == SCENARIOS[key].expected


@pytest.mark.parametrize("key", [k for k in SCENARIOS if k not in ("compaction", "step_limit")])
def test_only_the_compaction_scenarios_compact_at_default_budget(key):
    assert not any(s.compaction for s in run_scenario(key).steps)


def test_compaction_scenario_compacts_once_and_keeps_going():
    result = run_scenario("compaction")
    fired = [s for s in result.steps if s.compaction]
    assert len(fired) == 1
    c = fired[0].compaction
    assert c.size_before > 2000 and c.size_after < c.size_before
    # After compaction the context is: system, task, the summary. Old turns are gone.
    assert fired[0].context[2] == {"role": "assistant", "content": SCENARIOS["compaction"].summary}
    assert len(fired[0].context) == 3


def test_huge_budget_never_compacts():
    assert not any(s.compaction for s in run_scenario("compaction", budget=10**9).steps)


def test_false_claim_is_caught_and_failure_fed_back():
    result = run_scenario("test_failure")
    claim = result.steps[1]
    assert claim.kind == "claim" and not claim.verification.passed
    failure = result.steps[2].context[-1]
    assert failure["role"] == "user" and failure["content"].startswith("TEST_FAILURE ")


def test_every_tool_call_gets_an_answer_keyed_by_id():
    result = run_scenario("parallel_calls")
    first = result.steps[0]
    assert [e.call_id for e in first.tool_events] == ["call_a", "call_b"]
    tool_msgs = [m for m in result.history if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_a", "call_b"]
    assert set(first.workspace) == {"NOTES.md", "slugify.py", "test_slugify.py"}


def test_tool_message_follows_the_assistant_turn_that_requested_it():
    history = run_scenario("happy").history
    assert history[0]["role"] == "assistant" and history[0]["tool_calls"][0]["id"] == "call_1"
    assert history[1] == {"role": "tool", "tool_call_id": "call_1", "content": history[1]["content"]}


def test_step_limit_returns_the_notebooks_message():
    result = run_scenario("step_limit", max_steps=4)
    assert result.outcome == "step_limit" and len(result.steps) == 4
    assert result.final == "Stopped: step limit reached."


def test_model_is_stateless_it_only_sees_the_context():
    model = ScriptedModel([message(tool_calls=[tool_call("c1", "write_file",
                                                         {"name": "slugify.py", "body": specs.CORRECT})]),
                           message("done")])
    run_agent(model, specs.SPECS[specs.DEFAULT_SPEC])
    first, second = model.calls
    assert len(first) == 2                       # system + task, nothing else
    assert second[:2] == first and len(second) == 4   # + the assistant turn + its tool result


def test_events_are_reported():
    events = []
    run_scenario("happy", on_event=events.append)
    assert events[0].startswith("[1] write_file: wrote ")
    assert events[1] == "[2] model says done; tests PASS"


def test_step_limit_scenario_really_alternates_its_answers():
    result = run_scenario("step_limit")
    claims = [s.verification.evidence for s in result.steps if s.verification]
    assert "test_contradiction" in claims[0] and "test_basic" in claims[1]
