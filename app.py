"""Harness Engineering Explorer: a Streamlit app for seeing how an agent harness wraps a model.

Run with:  uv run streamlit run app.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st

from harness_lab import harness, specs
from harness_lab.models import DEFAULT_LIVE_MODEL, LiveModel, find_api_key, message, tool_call
from harness_lab.pipelines import new_workspace, run_agent, run_scenario, run_verification
from harness_lab.scenarios import SCENARIOS

ROOT = Path(__file__).parent
DOC_LINK = "docs/how-harness-engineering-works.md"

st.set_page_config(page_title="Harness Engineering Explorer", page_icon="🧰", layout="wide")

# Results kept in session_state are harness_lab objects. If that code changes while the app is
# running, old results keep their old shape and could crash a tab, so drop them on code changes.
RESULT_KEYS = ("t2_last", "t3", "t4_live", "t5")


def code_version() -> str:
    files = sorted((ROOT / "harness_lab").glob("*.py"))
    return "|".join(f"{f.name}:{f.stat().st_mtime_ns}" for f in files)


if st.session_state.get("_code_version") != (version := code_version()):
    for key in RESULT_KEYS:
        st.session_state.pop(key, None)
    st.session_state["_code_version"] = version


# --- Shared rendering helpers -----------------------------------------------------------------
AVATARS = {"system": "⚙️", "user": "🧑", "assistant": "🤖", "tool": "🔧"}


def chars(obj) -> int:
    return len(json.dumps(obj))


def render_message(m: dict, label: str = "") -> None:
    role = m["role"]
    with st.chat_message(role, avatar=AVATARS.get(role, "💬")):
        head = f"**{role}**" + (f"  ·  `tool_call_id={m['tool_call_id']}`" if role == "tool" else "")
        st.markdown(f"{head}  ·  {chars(m)} chars {label}")
        content = m.get("content")
        if role == "user" and content and content.startswith("TEST_FAILURE"):
            st.code(content, language="text")
        elif role == "tool":
            st.code(content or "", language="text")
        elif content:
            st.markdown(content if role != "system" else f"```text\n{content}\n```")
        for call in m.get("tool_calls", []):
            fn = call["function"]
            st.markdown(f"🛠️ requests **`{fn['name']}`**  ·  `id={call['id']}`")
            try:
                args = json.loads(fn["arguments"])
            except json.JSONDecodeError:
                st.caption("arguments (not valid JSON):")
                st.code(fn["arguments"], language="text")
                continue
            for k, v in args.items():
                if isinstance(v, str) and "\n" in v:
                    st.caption(f"`{k}`:")
                    st.code(v, language="python" if str(args.get("name", "")).endswith(".py") else "text")
                else:
                    st.caption(f"`{k}` = `{v}`")


def render_context(context: list[dict], new_from: int | None = None) -> None:
    for i, m in enumerate(context):
        render_message(m, "🆕 new since the previous call" if new_from is not None and i >= new_from else "")


def render_files(files: dict[str, str], key: str) -> None:
    if not files:
        st.caption("(workspace is empty)")
        return
    tabs = st.tabs(list(files))
    for tab, (name, body) in zip(tabs, files.items()):
        with tab:
            st.code(body, language="python" if name.endswith(".py") else "markdown")


def outcome_banner(result) -> None:
    if result.outcome == "verified":
        st.success(f"✅ **Verified** after {len(result.steps)} steps. `run()` returned: {result.final!r}")
    else:
        st.warning(f"⚠️ **Stopped unverified** after {len(result.steps)} steps. "
                   f"`run()` returned: {result.final!r}")


@st.cache_data(show_spinner=False)
def recorded(key: str, budget: int = 2000):
    return run_scenario(key, budget=budget)


# --- Sidebar: live model settings ---------------------------------------------------------------
with st.sidebar:
    st.header("🧰 Settings")
    st.markdown("Tabs ①–④ need **no model**. Tab ⑤ runs with a **Scripted** model (offline, free, "
                "the same every time) or a **Live** OpenAI model.")
    st.subheader("Live model (optional)")
    found_key, where = find_api_key(ROOT)
    if found_key:
        st.success(f"OpenAI key found ({where}).")
        api_key = found_key
    else:
        api_key = st.text_input("OPENAI_API_KEY", type="password",
                                help="Kept in this browser session only. Or set the environment "
                                     "variable, or put it in a .env file in the project folder.")
        if not api_key:
            st.info("No key: Live mode is off. Everything else works.")
    live_model_name = st.text_input("Model", DEFAULT_LIVE_MODEL,
                                    help="Any OpenAI chat model that supports tool calling.")
    st.divider()
    st.markdown(f"New here? Read the guide: `{DOC_LINK}`. Terms are defined in `GLOSSARY.md`.")


# --- Header -------------------------------------------------------------------------------------
st.title("🧰 Harness Engineering Explorer")
st.markdown("> **The model reasons. The harness does everything else:** it assembles the context, "
            "runs the tools the model asks for, checks the result against evidence rather than "
            "the model's confidence, compacts its history when it grows too long, and decides "
            "when to stop.")
st.caption("Follow the tabs in order: each one opens up one part of the harness, and tab ⑤ puts "
           "them together.")

t1, t2, t3, t4, t5 = st.tabs(["① Context assembly", "② Tool contract", "③ Verification",
                              "④ Compaction", "⑤ Agent loop"])

# =================================================================================================
# ① Context assembly
# =================================================================================================
with t1:
    st.subheader("① Context assembly: what the model sees")
    st.markdown(
        "The model is **stateless**. It remembers nothing between calls. Every step, the harness "
        "rebuilds the full list of messages (the **context**) from scratch: the system prompt "
        "plus the **skill**, the **task**, and the **history** so far. "
        "If something isn't in this list, the model doesn't know it.")
    st.caption("The contexts below come from a recorded run of scenario 2 (*Fix after a test "
               "failure*), with the real harness and a scripted model.")

    rec = recorded("test_failure")
    task = specs.task_for(specs.SPECS[specs.DEFAULT_SPEC])

    c_left, c_right = st.columns([1, 2])
    with c_left:
        use_skill = st.checkbox("Inject the skill", value=True, key="t1_use_skill")
        skill = st.text_area("Skill text (edit it and watch the system message change)",
                             harness.SKILLS["python"], key="t1_skill", disabled=not use_skill)
        n = len(rec.steps)
        step = st.slider("Step (one model call per step)", 1, n, 1, key="t1_step")
        record = rec.steps[step - 1]
        history = record.context[2:]
        context = harness.assemble(task, history, skill if use_skill else None)
        prev_len = len(rec.steps[step - 2].context) if step > 1 else 0

        parts = [{"part": "system prompt + skill", "messages": 1, "chars": chars(context[0])},
                 {"part": "task", "messages": 1, "chars": chars(context[1])},
                 {"part": "history", "messages": len(history), "chars": harness.history_size(history)}]
        st.markdown(f"**Context for step {step}: {len(context)} messages, "
                    f"{sum(p['chars'] for p in parts)} chars**")
        st.dataframe(pd.DataFrame(parts), hide_index=True, width="stretch")
        st.markdown(
            f"- The first **2** messages are the same every step: the harness rebuilds them.\n"
            f"- The history grows by every assistant reply, tool result and test failure.\n"
            f"- 🆕 marks what's new since step {step - 1}." if step > 1 else
            "- On step 1 there is no history yet: the model only knows the system prompt and task.")
        with st.expander("The code (`assemble`)"):
            st.code('''def assemble(task, history):
    system = "You write Python to satisfy the given test."
    return [{"role": "system", "content": f"{system}\\n{SKILLS['python']}"},
            {"role": "user", "content": task}] + history''', language="python")
    with c_right:
        render_context(context, new_from=prev_len if step > 1 else None)
        with st.expander("Raw JSON sent to the API"):
            st.json(context)

# =================================================================================================
# ② Tool contract
# =================================================================================================
with t2:
    st.subheader("② Tool contract: the model requests, the harness acts")
    st.markdown(
        "The model can't touch files. It can only **ask**. The harness keeps two things in step: "
        "`TOOLS` (what it will actually run) and `TOOL_SCHEMA` (what the model is told it may "
        "request). `execute()` answers only for names it recognises, and **returns errors as text** "
        "so the model can read them and try again, instead of crashing the run.")

    a, b = st.columns(2)
    with a:
        st.markdown("**`TOOLS`: what the harness will run**")
        st.code('TOOLS = {"write_file": write_file}', language="python")
        st.code('''def write_file(name, body):
    (WORKSPACE / name).write_text(body)
    return f"wrote {WORKSPACE / name}"''', language="python")
    with b:
        st.markdown("**`TOOL_SCHEMA`: what the model may request**")
        st.json(harness.TOOL_SCHEMA, expanded=False)

    st.divider()
    st.markdown("#### Send a tool call through the real `execute()`")
    PRESETS = {
        "Good call": ("write_file", json.dumps({"name": "slugify.py", "body": specs.CORRECT}, indent=1)),
        "Unknown tool": ("run_shell", json.dumps({"command": "rm -rf /"})),
        "Malformed JSON": ("write_file", '{"name": "slugify.py", "body": "def slug'),
        "Missing argument": ("write_file", json.dumps({"name": "slugify.py"})),
        "Path outside the workspace (app addition)": ("write_file",
                                                      json.dumps({"name": "../escape.py", "body": "x"})),
    }
    preset = st.radio("Start from", list(PRESETS), horizontal=True, key="t2_preset")
    p_name, p_args = PRESETS[preset]
    c1, c2 = st.columns([1, 2])
    with c1:
        name = st.text_input("Tool name the model asks for", p_name, key=f"t2_name_{preset}")
    with c2:
        args = st.text_area("Arguments (raw JSON text, exactly as the model would send it)", p_args,
                            height=150, key=f"t2_args_{preset}")

    if "t2_ws" not in st.session_state or not st.session_state["t2_ws"].exists():
        st.session_state["t2_ws"] = new_workspace()
    ws: Path = st.session_state["t2_ws"]
    bc1, bc2, _ = st.columns([1, 1, 3])
    if bc1.button("▶️ Execute", type="primary", key="t2_go"):
        call = message(tool_calls=[tool_call("call_demo", name, args)]).tool_calls[0]
        result = harness.execute(call, harness.make_tools(ws))
        if name not in harness.make_tools(ws):
            branch = "unknown name: `TOOLS.get()` returned `None`, so the harness never ran anything"
        elif result.startswith("error:"):
            branch = "the tool raised an exception; `execute()` caught it and turned it into text"
        else:
            branch = "the tool ran"
        st.session_state["t2_last"] = (name, args, result, branch)
    if bc2.button("🧹 Empty the workspace", key="t2_reset"):
        shutil.rmtree(ws, ignore_errors=True)
        st.session_state["t2_ws"] = ws = new_workspace()
        st.session_state.pop("t2_last", None)

    if last := st.session_state.get("t2_last"):
        l_name, _, result, branch = last
        ok = not result.startswith("error:")
        (st.success if ok else st.warning)(f"**Tool result:** `{result}`")
        st.markdown(f"**What happened inside `execute()`:** {branch}.")
        st.markdown("**The message that goes back into the history** (the model reads it next step):")
        st.json({"role": "tool", "tool_call_id": "call_demo", "content": result})
        if not ok:
            st.info("The run keeps going. Had `execute()` raised the exception instead of returning "
                    "it, the whole run would have ended here, and the model would never get the "
                    "chance to correct itself.")
    st.markdown(f"**Workspace now** (`{ws.name}`):")
    render_files(harness.snapshot(ws), "t2_files")

# =================================================================================================
# ③ Verification
# =================================================================================================
with t3:
    st.subheader("③ Verification: evidence, not the model's confidence")
    st.markdown(
        "When the model replies without a tool call, it is **claiming** it's finished. The harness "
        "doesn't take its word for it. It runs the **spec** (the test suite) in a subprocess. The "
        "exit code is the **evidence** that settles it. On failure, the test output goes back to "
        "the model as a `TEST_FAILURE` message.")
    a, b = st.columns(2)
    with a:
        spec_name = st.selectbox("Spec (test_slugify.py)", list(specs.SPECS), key="t3_spec")
        spec_text = st.text_area("Edit the spec", specs.SPECS[spec_name], height=330,
                                 key=f"t3_spec_text_{spec_name}")
    with b:
        cand_name = st.selectbox("Candidate slugify.py (what the model wrote)", list(specs.CANDIDATES),
                                 key="t3_cand")
        cand = specs.CANDIDATES[cand_name]
        if cand is None:
            st.caption("No file: the model claimed it was done without writing anything.")
            cand_text = None
        else:
            cand_text = st.text_area("Edit the candidate", cand, height=290, key=f"t3_cand_text_{cand_name}")
    if st.button("▶️ Claim done & verify", type="primary", key="t3_go"):
        with st.spinner("Running the tests in a subprocess…"):
            st.session_state["t3"] = run_verification(spec_text, cand_text)
    if report := st.session_state.get("t3"):
        c_claim, c_evidence = st.columns(2)
        with c_claim:
            st.markdown("#### 🤖 The claim")
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(f"*{SCENARIOS['happy'].replies[-1].content}*")
            st.caption("The model sounds just as confident whether the code works or not.")
        with c_evidence:
            st.markdown("#### 🧪 The evidence")
            m1, m2, m3 = st.columns(3)
            m1.metric("Exit code", report.exit_code)
            m2.metric("Tests run", report.ran)
            m3.metric("Verdict", "PASS ✅" if report.passed else "FAIL ❌")
            if report.failures:
                st.dataframe(pd.DataFrame(report.failures, columns=["test", "kind"]), hide_index=True)
        st.markdown("**Test output (stderr)**")
        st.code(report.evidence or "(empty)", language="text")
        if report.passed:
            st.success("Accepted: `run()` returns the model's reply and stops.")
        else:
            st.error("Rejected. This message is appended to the history, and the loop continues:")
            st.json({"role": "user", "content": f"TEST_FAILURE {report.evidence}"})
            st.caption("It is a `user` message because the model's 'I'm done' reply had no tool "
                       "call for a `tool` message to answer.")

# =================================================================================================
# ④ Compaction
# =================================================================================================
with t4:
    st.subheader("④ Compaction: keeping the context in bounds")
    st.markdown(
        "Every step adds to the history, and the whole history is sent again on every call. When "
        "it grows past the **budget**, the harness asks the model to **summarise** it and replaces "
        "the whole history with that one summary. The summary keeps the objective, the dead ends "
        "and why, and the file paths. The files themselves stay on disk, so they don't need to be "
        "carried along.")
    st.caption("The history below is from scenario 6 (*Compaction*), recorded with compaction "
               "switched off so you can see it grow.")
    long = recorded("compaction", budget=10**9)
    budget = st.slider("Budget (characters of history)", 200, 6000, 2000, 100, key="t4_budget")
    sizes = [s.history_size for s in long.steps]
    df = pd.DataFrame({"step": [s.step for s in long.steps], "history size (chars)": sizes,
                       "budget": [budget] * len(sizes)}).set_index("step")
    st.line_chart(df, height=230)
    st.caption("The size is checked at the **start** of each step, before the model is called. "
               f"Characters, not tokens (roughly ÷4 for tokens: {budget} chars ≈ {budget // 4} tokens).")

    fire = next((s for s in long.steps if s.history_size > budget), None)
    if fire is None:
        st.info("With this budget compaction never fires in this run. Lower the budget.")
    else:
        before = fire.context[2:]
        st.markdown(f"#### Compaction fires at the start of step {fire.step} "
                    f"({fire.history_size} chars > {budget})")
        summary = SCENARIOS["compaction"].summary
        live_key = f"{fire.step}"
        if api_key and st.button("✨ Write the summary with the live model instead", key="t4_live_btn"):
            with st.spinner("Asking the model to summarise…"):
                st.session_state["t4_live"] = (live_key, harness.compact(
                    LiveModel(api_key, live_model_name), before)[0]["content"])
        live = st.session_state.get("t4_live")
        if live and live[0] == live_key:
            summary, source = live[1], "live model"
        else:
            source = "scripted model"
        after = [{"role": "assistant", "content": summary}]
        a, b = st.columns(2)
        with a:
            st.markdown(f"**Before: {len(before)} messages, {harness.history_size(before)} chars**")
            with st.container(height=520):
                render_context(before)
        with b:
            st.markdown(f"**After: 1 message, {harness.history_size(after)} chars** ({source})")
            render_context(after)
            st.markdown("**The prompt that produced it** (sent with *no tools*, so the model "
                        "summarises instead of acting):")
            st.code(harness.COMPACT_PROMPT, language="text")
            st.markdown("**What's kept:** the objective · what was tried and why it failed · "
                        "which files are on disk.\n\n"
                        "**What's lost:** the exact code of old attempts and the full test output. "
                        "That's fine: the current file is still on disk, and the next test run "
                        "will produce fresh evidence.")

# =================================================================================================
# ⑤ Agent loop
# =================================================================================================
with t5:
    st.subheader("⑤ The agent loop: reason, act, verify, repeat")
    st.markdown(
        "All the parts together. Each **step** calls the model exactly once. If it asks for tools, "
        "the harness runs them and loops. If it claims to be done, the harness verifies. The loop "
        "ends when the tests pass or the **step limit** is reached.")
    a, b, c = st.columns([2, 1, 1])
    with a:
        mode = st.radio("Model", ["Scripted", "Live"], horizontal=True, key="t5_mode",
                        help="Scripted: a fake model replays a fixed script through the real harness. "
                             "Live: a real OpenAI model.")
        if mode == "Scripted":
            sc_key = st.selectbox("Scenario", list(SCENARIOS), format_func=lambda k: SCENARIOS[k].title,
                                  key="t5_scenario")
            st.caption(f"**What it shows:** {SCENARIOS[sc_key].teaches}  ·  spec: "
                       f"*{SCENARIOS[sc_key].spec}*")
        else:
            live_spec = st.selectbox("Spec", list(specs.SPECS), key="t5_spec")
            if not api_key:
                st.warning("Add an OpenAI key in the sidebar to use Live mode.")
    max_steps = b.slider("Step limit", 1, 15, 10, key="t5_steps")
    budget5 = c.number_input("Budget (chars)", 200, 20000, 2000, 100, key="t5_budget",
                             help="Lower it to watch compaction fire.")

    if st.button("▶️ Run the agent loop", type="primary", key="t5_go",
                 disabled=(mode == "Live" and not api_key)):
        with st.status("Running…", expanded=True) as status:
            log = st.empty()
            lines: list[str] = []

            def on_event(msg: str) -> None:
                lines.append(msg)
                log.code("\n".join(lines), language="text")

            try:
                if mode == "Scripted":
                    result = run_scenario(sc_key, max_steps=max_steps, budget=budget5, on_event=on_event)
                else:
                    result = run_agent(LiveModel(api_key, live_model_name), specs.SPECS[live_spec],
                                       max_steps=max_steps, budget=budget5, on_event=on_event)
                st.session_state["t5"] = result
                status.update(label=f"Done: {result.outcome}", state="complete", expanded=False)
            except Exception as exc:     # e.g. a bad API key: show it, don't crash the app
                status.update(label="Failed", state="error")
                st.error(f"The model call failed: {exc}")

    if result := st.session_state.get("t5"):
        outcome_banner(result)
        rows = []
        for s in result.steps:
            if s.tool_events:
                did = ", ".join(f"{e.name}()" for e in s.tool_events)
                got = " | ".join(e.result[:60] for e in s.tool_events)
            else:
                did = "claims done"
                got = "tests PASS ✅" if s.verification.passed else "tests FAIL ❌ → TEST_FAILURE"
            rows.append({"step": s.step, "history chars": s.history_size,
                         "compacted": "🗜️" if s.compaction else "", "model": did, "harness": got})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        n = len(result.steps)
        sel = st.slider("Inspect a step", 1, n, 1, key="t5_step") if n > 1 else 1
        s = result.steps[sel - 1]

        def node(name: str, label: str, on: bool) -> str:
            style = 'style=filled fillcolor="#ffd966"' if on else 'color="#999999" fontcolor="#999999"'
            return f'{name} [label="{label}" shape=box {style}];'

        is_claim = not s.tool_events
        passed = bool(s.verification and s.verification.passed)
        dot = "digraph { rankdir=LR; node [fontname=Helvetica fontsize=11];\n" + "\n".join([
            node("check", f"budget check\\n{s.history_size} chars", True),
            node("compact", "compact()", bool(s.compaction)),
            node("assemble", "assemble()", True),
            node("llm", "llm()", True),
            node("execute", "execute()\\nper tool call", not is_claim),
            node("verify", "verify()", is_claim),
            node("fail", "TEST_FAILURE\\n→ history", is_claim and not passed),
            node("stop", "return", passed),
        ]) + """
check -> compact [label="> budget"]; check -> assemble; compact -> assemble;
assemble -> llm; llm -> execute [label="tool calls"]; llm -> verify [label="no tool call"];
verify -> fail [label="fail"]; verify -> stop [label="pass"];
}"""
        st.graphviz_chart(dot)

        if s.compaction:
            c_ = s.compaction
            with st.expander(f"🗜️ Compaction fired: {c_.size_before} → {c_.size_after} chars", expanded=True):
                st.markdown("**The summary that replaced the history:**")
                st.markdown(c_.summary)
                st.caption(f"It replaced {len(c_.history_before)} messages.")
        prev_len = len(result.steps[sel - 2].context) if sel > 1 and not s.compaction else None
        with st.expander(f"📨 Context sent to the model ({len(s.context)} messages, "
                         f"{chars(s.context)} chars)"):
            render_context(s.context, new_from=prev_len)
        st.markdown("**🤖 The model replied:**")
        render_message(s.reply)
        if s.tool_events:
            st.markdown("**🔧 The harness ran each tool call and answered it:**")
            for e in s.tool_events:
                ok = not e.result.startswith("error:")
                (st.success if ok else st.warning)(f"`{e.call_id}` · `{e.name}` → {e.result}")
        if s.verification:
            st.markdown("**🧪 The model claimed it was done, so the harness ran the tests:**")
            (st.success if s.verification.passed else st.error)(
                "PASS: accepted" if s.verification.passed else "FAIL: sent back as TEST_FAILURE")
            st.code(s.verification.evidence, language="text")
        st.markdown(f"**📁 Workspace at the end of step {sel}:**")
        render_files(s.workspace, f"t5_files_{sel}")
