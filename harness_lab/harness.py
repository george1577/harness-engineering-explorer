"""The harness from the notebook, kept as close to the original as the app allows.

Every function here has the same name and does the same job as in
`examples/19_harness_engineering/harness_engineering.ipynb`. The differences, all listed in
section 8 of docs/how-harness-engineering-works.md, are:

* the model (`llm`) is passed in, so the same loop runs with a scripted or a live model;
* the workspace is a parameter instead of a global, so every run gets a fresh directory;
* the test subprocess has a timeout, so model-written code can't hang the app;
* the test subprocess runs with `python -B` (no `__pycache__`), so a rewritten file of the same
  size, written within the same second, is never shadowed by stale cached bytecode;
* `write_file` refuses paths that leave the workspace;
* `run()` returns a per-step trace instead of printing, and can report progress through
  `on_event`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Callable, Protocol

SYSTEM = "You write Python to satisfy the given test."

SKILLS = {"python": "Write plain functions. No classes. Type-annotate."}

COMPACT_PROMPT = ("Summarize for a fresh context: the current objective, the "
                  "approaches already ruled out and why, and the paths of files "
                  "already written to disk.")

TEST_TIMEOUT = 10  # seconds


class Model(Protocol):
    """The model: reasoning only. Stateless: it sees the context it is handed, nothing else.

    Returns an OpenAI-shaped assistant message (`.content`, `.tool_calls`, `.model_dump()`).
    """

    def __call__(self, context: list[dict], tools: list[dict] | None = None) -> Any: ...


# --- Context injection: what the model sees, assembled on every call --------------------------
def assemble(task: str, history: list[dict], skill: str | None = SKILLS["python"]) -> list[dict]:
    system = SYSTEM if not skill else f"{SYSTEM}\n{skill}"
    return [{"role": "system", "content": system},
            {"role": "user", "content": task}] + history


# --- Interacting with the real world: the model requests, the harness acts --------------------
def write_file(workspace: Path, name: str, body: str) -> str:
    target = (workspace / name).resolve()
    if not target.is_relative_to(workspace.resolve()):     # app addition: stay in the workspace
        raise ValueError(f"{name!r} is outside the workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    return f"wrote {workspace.name}/{name}"


def run_tests(workspace: Path, timeout: float = TEST_TIMEOUT) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover",   # -B: app addition
             "-s", str(workspace), "-t", str(workspace)],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:                       # app addition
        return 1, f"TIMEOUT: the test run took longer than {timeout:g} s and was killed."
    return proc.returncode, proc.stderr.strip()


def make_tools(workspace: Path) -> dict[str, Callable[..., str]]:
    """TOOLS from the notebook, bound to one workspace. What the harness will run."""
    return {"write_file": partial(write_file, workspace)}


TOOL_SCHEMA = [{                            # what the model may request
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write a file into the workspace, overwriting it.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "File name in the workspace."},
                "body": {"type": "string",
                         "description": "Full contents of the file."},
            },
            "required": ["name", "body"],
        },
    },
}]


def execute(call: Any, tools: dict[str, Callable[..., str]]) -> str:
    fn = tools.get(call.function.name)      # a permission check would go here
    if fn is None:
        return f"error: no such tool {call.function.name}"
    try:
        return fn(**json.loads(call.function.arguments))  # a real harness
    except Exception as exc:                              # sandboxes this
        return f"error: {exc}"              # the model sees this and can retry


# --- Organize: replace the history with a shorter representation of it -----------------------
def compact(llm: Model, history: list[dict]) -> list[dict]:
    reply = llm(history + [{"role": "user", "content": COMPACT_PROMPT}])  # no tools:
    return [{"role": "assistant", "content": reply.content}]             # summarize


# --- Check and verify: evidence, not the model's confidence ----------------------------------
def verify(workspace: Path, timeout: float = TEST_TIMEOUT) -> tuple[bool, str]:
    code, output = run_tests(workspace, timeout)
    return code == 0, output


def history_size(history: list[dict]) -> int:
    """The notebook's measure of history size: characters of JSON, not tokens."""
    return sum(len(json.dumps(m)) for m in history)


# --- Trace records (app addition: the notebook prints instead) -------------------------------
@dataclass
class ToolEvent:
    call_id: str
    name: str
    arguments: str          # raw JSON text, exactly as the model sent it
    result: str


@dataclass
class Compaction:
    size_before: int
    history_before: list[dict]
    summary: str
    size_after: int


@dataclass
class Verification:
    passed: bool
    evidence: str


@dataclass
class StepRecord:
    step: int
    history_size: int                       # measured at the start of the step
    compaction: Compaction | None = None
    context: list[dict] = field(default_factory=list)
    reply: dict = field(default_factory=dict)
    tool_events: list[ToolEvent] = field(default_factory=list)
    verification: Verification | None = None
    workspace: dict[str, str] = field(default_factory=dict)   # files at the end of the step

    @property
    def kind(self) -> str:
        return "tool calls" if self.tool_events else "claim"


@dataclass
class RunResult:
    outcome: str            # "verified" or "step_limit"
    final: str              # what run() returns in the notebook
    steps: list[StepRecord]
    history: list[dict]     # the history at the end of the run


def snapshot(workspace: Path) -> dict[str, str]:
    files = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files[str(path.relative_to(workspace))] = path.read_text(errors="replace")
    return files


# --- The agent loop ---------------------------------------------------------------------------
def run(task: str, llm: Model, workspace: Path, max_steps: int = 10, budget: int = 2000,
        skill: str | None = SKILLS["python"], timeout: float = TEST_TIMEOUT,
        on_event: Callable[[str], None] | None = None) -> RunResult:
    log = on_event or (lambda _msg: None)
    tools = make_tools(workspace)
    history: list[dict] = []
    steps: list[StepRecord] = []
    for step in range(1, max_steps + 1):
        size = history_size(history)                      # chars, not tokens
        record = StepRecord(step=step, history_size=size)
        steps.append(record)
        if size > budget:                                 # lower it to watch
            before = history
            history = compact(llm, history)               # compaction fires
            record.compaction = Compaction(size, before, history[0]["content"] or "",
                                           history_size(history))
            log(f"[{step}] compacted {size} chars of history")

        context = assemble(task, history, skill)
        record.context = context
        reply = llm(context, TOOL_SCHEMA)                    # model reasons
        message = reply.model_dump(exclude_none=True)        # the API wants
        history.append(message)                              # its own turn back
        record.reply = message

        if reply.tool_calls:
            for call in reply.tool_calls:                 # answer every one
                result = execute(call, tools)             # action
                record.tool_events.append(ToolEvent(
                    call.id, call.function.name, call.function.arguments, result))
                log(f"[{step}] {call.function.name}: {result}")
                history.append({"role": "tool", "tool_call_id": call.id,
                                "content": result})
            record.workspace = snapshot(workspace)
            continue

        passed, evidence = verify(workspace, timeout)     # check before accepting
        record.verification = Verification(passed, evidence)
        record.workspace = snapshot(workspace)
        log(f"[{step}] model says done; tests {'PASS' if passed else 'FAIL'}")
        if passed:
            return RunResult("verified", reply.content or "", steps, history)
        history.append({"role": "user",
                        "content": f"TEST_FAILURE {evidence}"})

    return RunResult("step_limit", "Stopped: step limit reached.", steps, history)  # error recovery
