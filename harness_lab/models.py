"""The two kinds of model the harness can drive.

Both return the same type, OpenAI's `ChatCompletionMessage`, so `harness.run()` cannot tell
them apart. That is the point: the harness is identical in both modes (see docs/adr/0001).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from openai.types.chat import ChatCompletionMessage

DEFAULT_LIVE_MODEL = "gpt-4o-mini"


def message(content: str | None = None, tool_calls: list[dict] | None = None) -> ChatCompletionMessage:
    """Build an assistant message shaped exactly like a real API reply."""
    data: dict = {"role": "assistant", "content": content}
    if tool_calls:
        data["tool_calls"] = tool_calls
    return ChatCompletionMessage.model_validate(data)


def tool_call(call_id: str, name: str, arguments: str | dict) -> dict:
    """One tool call. `arguments` may be a dict, or raw (possibly broken) JSON text."""
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}


@dataclass
class ScriptedModel:
    """A fake model that replays a fixed list of replies, one per step.

    It ignores the context it is shown, which a real model never does. The harness around it is
    real: files are really written, tests really run, and the outcome depends on them.
    Called without tools (that is how `compact()` calls it), it returns the scenario's summary.
    When the script runs out it keeps repeating its last reply.
    """

    replies: list[ChatCompletionMessage]
    summary: str = ""
    calls: list[list[dict]] = field(default_factory=list)   # every context it was handed
    _next: int = 0

    def __call__(self, context: list[dict], tools: list[dict] | None = None) -> ChatCompletionMessage:
        self.calls.append(context)
        if tools is None:
            return message(self.summary or "Summary: (no summary scripted)")
        reply = self.replies[min(self._next, len(self.replies) - 1)]
        self._next += 1
        return reply


class LiveModel:
    """The notebook's `llm()`: one OpenAI chat-completions call per step."""

    def __init__(self, api_key: str, model: str = DEFAULT_LIVE_MODEL):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.calls: list[list[dict]] = []

    def __call__(self, context: list[dict], tools: list[dict] | None = None) -> ChatCompletionMessage:
        self.calls.append(context)
        reply = self.client.chat.completions.create(
            model=self.model, messages=context, **({"tools": tools} if tools else {}))
        return reply.choices[0].message


def find_api_key(project_dir: Path) -> tuple[str | None, str]:
    """Look for OPENAI_API_KEY: environment first, then the project's git-ignored .env.

    Returns (key, where it was found). The key is never logged or displayed.
    """
    if key := os.environ.get("OPENAI_API_KEY", "").strip():
        return key, "environment variable"
    env_file = project_dir / ".env"
    if env_file.exists():
        from dotenv import dotenv_values

        if key := (dotenv_values(env_file).get("OPENAI_API_KEY") or "").strip():
            return key, ".env file"
    return None, ""
