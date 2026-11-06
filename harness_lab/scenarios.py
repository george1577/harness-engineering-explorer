"""Named scripts for the ScriptedModel. Each one is built to make one harness path fire.

The scripted model ignores what it is shown, but everything else is real: the files are written,
the tests run in a subprocess, and the harness decides what happens next from the actual results.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import specs
from .models import ScriptedModel, message, tool_call


DEFAULT_SUMMARY = ("Objective: implement slugify(text) in slugify.py so every test in "
                   "test_slugify.py passes.\n"
                   "Ruled out: nothing yet.\n"
                   "Files on disk: slugify.py (if written), test_slugify.py (the spec).")


@dataclass(frozen=True)
class Scenario:
    title: str
    teaches: str            # one line: which harness path this makes visible
    replies: tuple          # ChatCompletionMessage objects, one per step
    summary: str = DEFAULT_SUMMARY   # what the model says when compact() asks it to summarize
    spec: str = specs.DEFAULT_SPEC
    expected: str = "verified"

    def model(self) -> ScriptedModel:
        return ScriptedModel(list(self.replies), self.summary)


def write(call_id: str, body: str, name: str = specs.TARGET_FILE) -> dict:
    return tool_call(call_id, "write_file", {"name": name, "body": body})


DONE = "I've implemented slugify in slugify.py. It should pass all the tests."

GOOD = specs.CORRECT

# Long-winded attempts for the compaction scenario: big bodies make the history grow fast.
VERBOSE_ATTEMPT_1 = '''\
def slugify(text: str) -> str:
    """Turn text into a URL slug.

    Approach 1: lowercase the text, then replace every space with a hyphen.
    """
    lowered = text.lower()
    hyphenated = lowered.replace(" ", "-")
    return hyphenated
'''

VERBOSE_ATTEMPT_2 = '''\
def slugify(text: str) -> str:
    """Turn text into a URL slug.

    Approach 2: keep only letters, digits and spaces (this removes the comma and the
    exclamation mark), strip the ends, then replace each remaining space with a hyphen.
    Runs of several spaces in the middle are not collapsed in this version.
    """
    kept_characters = [c for c in text.lower() if c.isalnum() or c == " "]
    cleaned = "".join(kept_characters).strip()
    return cleaned.replace(" ", "-")
'''

UNDERSCORE = '''\
import re


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
'''

SCENARIOS: dict[str, Scenario] = {
    "happy": Scenario(
        title="1. Happy path",
        teaches="The ordinary run: write the file, claim done, the tests confirm it.",
        replies=(
            message(tool_calls=[write("call_1", GOOD)]),
            message(DONE),
        ),
    ),
    "test_failure": Scenario(
        title="2. Fix after a test failure",
        teaches="A false claim is caught by verification; the TEST_FAILURE evidence leads to a fix.",
        replies=(
            message(tool_calls=[write("call_1", specs.NO_COLLAPSE)]),
            message(DONE),
            message(tool_calls=[write("call_2", GOOD)]),
            message("Fixed: runs of spaces now collapse to a single hyphen."),
        ),
    ),
    "unknown_tool": Scenario(
        title="3. Unknown tool",
        teaches="The model asks for a tool the harness doesn't have; it gets an error as text and adapts.",
        replies=(
            message(tool_calls=[tool_call("call_1", "run_shell",
                                          {"command": "echo 'def slugify...' > slugify.py"})]),
            message(tool_calls=[write("call_2", GOOD)]),
            message(DONE),
        ),
    ),
    "bad_arguments": Scenario(
        title="4. Malformed arguments",
        teaches="Broken JSON and a missing argument come back as error text; the model retries correctly.",
        replies=(
            message(tool_calls=[tool_call("call_1", "write_file",
                                          '{"name": "slugify.py", "body": "import re\\n\\ndef slug')]),
            message(tool_calls=[tool_call("call_2", "write_file", {"name": "slugify.py"})]),
            message(tool_calls=[write("call_3", GOOD)]),
            message(DONE),
        ),
    ),
    "premature_claim": Scenario(
        title="5. Claims done too early",
        teaches="The model says it's finished before writing anything; the tests can't even import it.",
        replies=(
            message("Here is the implementation:\n\n```python\n" + GOOD + "```\nAll tests pass."),
            message(tool_calls=[write("call_1", GOOD)]),
            message(DONE),
        ),
    ),
    "compaction": Scenario(
        title="6. Compaction",
        teaches="Long failed attempts push the history over the budget; it's replaced by a summary.",
        replies=(
            message(tool_calls=[write("call_1", VERBOSE_ATTEMPT_1)]),
            message("Approach 1 is written to slugify.py: it lowercases the text and turns spaces "
                    "into hyphens. I believe it satisfies the suite."),
            message(tool_calls=[write("call_2", VERBOSE_ATTEMPT_2)]),
            message("Approach 2 is written to slugify.py: it now removes punctuation before "
                    "hyphenating. I believe all three tests pass now."),
            message(tool_calls=[write("call_3", GOOD)]),
            message("Approach 3 replaces every run of non-alphanumeric characters with a single "
                    "hyphen and strips hyphens from the ends. Done."),
        ),
        summary=("Objective: implement slugify(text) in slugify.py so test_slugify.py passes "
                 "(lowercase, punctuation removed, runs of spaces become one hyphen, no hyphens at "
                 "the ends).\n"
                 "Ruled out: (1) lower() + replace(' ', '-') keeps punctuation and turns runs of "
                 "spaces into several hyphens. (2) Dropping punctuation then replacing spaces still "
                 "fails test_collapses_space.\n"
                 "Files on disk: slugify.py (approach 2, failing), test_slugify.py (the spec)."),
    ),
    "step_limit": Scenario(
        title="7. Never passes (step limit)",
        teaches="The spec is impossible; the model flips between two answers until the step limit stops it.",
        spec="+ test_contradiction (impossible)",
        expected="step_limit",
        replies=tuple(
            m
            for i in range(5)
            for m in (
                message(tool_calls=[write(f"call_{i + 1}", GOOD if i % 2 == 0 else UNDERSCORE)]),
                message("Done: slugify now uses " + ("hyphens." if i % 2 == 0 else "underscores.")),
            )
        ),
        summary=("Objective: make every test in test_slugify.py pass.\n"
                 "Ruled out: hyphen separators fail test_contradiction; underscore separators fail "
                 "test_basic, test_punctuation and test_collapses_space.\n"
                 "Files on disk: slugify.py, test_slugify.py."),
    ),
    "parallel_calls": Scenario(
        title="8. Two tool calls in one reply",
        teaches="One reply asks for two tools; the harness answers each one, matched by tool_call_id.",
        replies=(
            message(tool_calls=[
                write("call_a", GOOD),
                write("call_b", "# Notes\n\nslugify: lowercase, then turn every run of "
                                "non-alphanumerics into one hyphen.\n", name="NOTES.md"),
            ]),
            message(DONE),
        ),
    ),
}
