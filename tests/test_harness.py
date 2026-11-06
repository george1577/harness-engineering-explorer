"""The harness pieces, one at a time, with no model at all."""

import json

import pytest

from harness_lab import harness, specs
from harness_lab.models import ScriptedModel, message, tool_call
from harness_lab.pipelines import new_workspace, parse_unittest, run_verification


def call(name, arguments):
    return message(tool_calls=[tool_call("c1", name, arguments)]).tool_calls[0]


def test_assemble_rebuilds_system_task_then_history():
    history = [{"role": "assistant", "content": "hi"}]
    context = harness.assemble("TASK", history)
    assert context[0] == {"role": "system", "content": f"{harness.SYSTEM}\n{harness.SKILLS['python']}"}
    assert context[1] == {"role": "user", "content": "TASK"}
    assert context[2:] == history


def test_assemble_without_skill_has_bare_system_prompt():
    assert harness.assemble("T", [], skill=None)[0]["content"] == harness.SYSTEM


def test_execute_runs_known_tool_and_writes_file():
    ws = new_workspace()
    result = harness.execute(call("write_file", {"name": "a.py", "body": "x = 1\n"}), harness.make_tools(ws))
    assert result == f"wrote {ws.name}/a.py"
    assert (ws / "a.py").read_text() == "x = 1\n"


@pytest.mark.parametrize("name, arguments, expected", [
    ("run_shell", {"command": "ls"}, "error: no such tool run_shell"),
    ("write_file", '{"name": "a.py", "bo', "error: Unterminated string"),
    ("write_file", {"name": "a.py"}, "error: write_file() missing 1 required positional argument: 'body'"),
    ("write_file", {"name": "../escape.py", "body": ""}, "error: '../escape.py' is outside the workspace"),
])
def test_execute_returns_errors_as_text(name, arguments, expected):
    result = harness.execute(call(name, arguments), harness.make_tools(new_workspace()))
    assert result.startswith(expected)


def test_verify_passes_correct_and_fails_naive():
    assert run_verification(specs.SPECS[specs.DEFAULT_SPEC], specs.CORRECT).passed
    report = run_verification(specs.SPECS[specs.DEFAULT_SPEC], specs.NAIVE)
    assert not report.passed and report.exit_code != 0
    assert report.ran == 3
    assert {n for n, _ in report.failures} == {"test_punctuation", "test_collapses_space"}


def test_missing_file_is_an_import_error():
    report = run_verification(specs.SPECS[specs.DEFAULT_SPEC], None)
    assert not report.passed and "slugify" in report.evidence


def test_unicode_spec_needs_the_accent_aware_version():
    spec = specs.SPECS["+ test_unicode (stricter)"]
    assert not run_verification(spec, specs.CORRECT).passed
    assert run_verification(spec, specs.CORRECT_UNICODE).passed


def test_infinite_loop_is_killed_by_timeout():
    ws = new_workspace(specs.SPECS[specs.DEFAULT_SPEC])
    (ws / specs.TARGET_FILE).write_text(specs.INFINITE_LOOP)
    code, output = harness.run_tests(ws, timeout=2)
    assert code != 0 and output.startswith("TIMEOUT")


def test_compact_replaces_history_with_one_summary_and_calls_without_tools():
    model = ScriptedModel([message("unused")], summary="SUMMARY")
    history = [{"role": "assistant", "content": "x" * 500}]
    assert harness.compact(model, history) == [{"role": "assistant", "content": "SUMMARY"}]
    assert model.calls[0][-1] == {"role": "user", "content": harness.COMPACT_PROMPT}


def test_history_size_counts_json_characters():
    m = {"role": "user", "content": "hi"}
    assert harness.history_size([m, m]) == 2 * len(json.dumps(m))


def test_parse_unittest():
    out = "F.E\n===\nFAIL: test_a (x.T.test_a)\n===\nERROR: test_b (x.T.test_b)\nRan 3 tests in 0.01s"
    assert parse_unittest(out) == (3, [("test_a", "FAIL"), ("test_b", "ERROR")])


def test_rewrite_of_same_size_is_not_shadowed_by_stale_bytecode():
    # Two same-length files written within one second: without `python -B` the second test run
    # would import the first version's cached .pyc.
    a = specs.CORRECT
    b = a.replace('"-"', '"_"')
    assert len(a) == len(b)
    ws = new_workspace(specs.SPECS[specs.DEFAULT_SPEC])
    (ws / specs.TARGET_FILE).write_text(a)
    assert harness.verify(ws)[0]
    (ws / specs.TARGET_FILE).write_text(b)
    assert not harness.verify(ws)[0]
