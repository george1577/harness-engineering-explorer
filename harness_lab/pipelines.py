"""One function per tab: sets up a fresh workspace and wires the harness to it."""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import harness, specs
from .harness import Model, RunResult
from .scenarios import SCENARIOS


def new_workspace(spec: str | None = None) -> Path:
    """A fresh, empty workspace (the notebook wipes `workspace/`). Optionally with the spec in it."""
    workspace = Path(tempfile.mkdtemp(prefix="workspace-"))
    if spec is not None:
        (workspace / specs.SPEC_FILE).write_text(spec)   # the spec is the input
    return workspace


def run_agent(llm: Model, spec: str, max_steps: int = 10, budget: int = 2000,
              skill: str | None = harness.SKILLS["python"],
              on_event: Callable[[str], None] | None = None) -> RunResult:
    """Tab ⑤: the full agent loop, in a throwaway workspace."""
    workspace = new_workspace(spec)
    try:
        return harness.run(specs.task_for(spec), llm, workspace, max_steps=max_steps,
                           budget=budget, skill=skill, on_event=on_event)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_scenario(key: str, max_steps: int = 10, budget: int = 2000,
                 on_event: Callable[[str], None] | None = None) -> RunResult:
    scenario = SCENARIOS[key]
    return run_agent(scenario.model(), specs.SPECS[scenario.spec], max_steps=max_steps,
                     budget=budget, on_event=on_event)


@dataclass
class TestReport:
    passed: bool
    exit_code: int
    evidence: str
    ran: int
    failures: list[tuple[str, str]]       # (test name, "FAIL" / "ERROR")


def run_verification(spec: str, candidate: str | None) -> TestReport:
    """Tab ③: put a candidate implementation next to a spec and run the real verify()."""
    workspace = new_workspace(spec)
    try:
        if candidate is not None:
            (workspace / specs.TARGET_FILE).write_text(candidate)
        code, output = harness.run_tests(workspace)
        return TestReport(code == 0, code, output, *parse_unittest(output))
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def parse_unittest(output: str) -> tuple[int, list[tuple[str, str]]]:
    ran = re.search(r"^Ran (\d+) tests?", output, re.M)
    failures = re.findall(r"^(FAIL|ERROR): (\S+)", output, re.M)
    return (int(ran.group(1)) if ran else 0), [(name, kind) for kind, name in failures]


def size_profile(history: list[dict]) -> list[int]:
    """History size (chars) after each turn: what the budget check would see as it grows."""
    return [harness.history_size(history[: i + 1]) for i in range(len(history))]
