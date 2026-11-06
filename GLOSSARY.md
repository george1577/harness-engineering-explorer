# Harness Engineering Explorer

A learning tool for seeing how an agent harness wraps a language model: what the model is shown, what it may ask for, how its work is checked, and when it stops.

## Language

### The two halves

**Model**:
The language model itself; it only reasons, reading the context it is handed and replying with either a tool call or plain text. It keeps no state between calls.
_Avoid_: Agent, AI, LLM (when meaning the whole system)

**Harness**:
Everything around the model: it assembles the context, runs requested tools, verifies results, compacts the history, and decides when to stop.
_Avoid_: Wrapper, framework, scaffold

**Agent loop**:
The harness's repeating cycle of reason, act, verify, until the work is verified or a limit is hit.
_Avoid_: Agent, run loop, chain

**Step**:
One pass of the agent loop, containing exactly one call to the model.
_Avoid_: Turn, iteration, round

**Turn**:
A single message in the history (an assistant reply, a tool result, or a user message).
_Avoid_: Step

### What the model sees

**Context**:
The complete list of messages sent to the model on one call, rebuilt from scratch every step.
_Avoid_: Prompt, history, memory

**History**:
The growing part of the context that the harness owns: assistant replies, tool results, and test failures.
_Avoid_: Context, transcript, memory

**Context injection**:
Assembling the context from the system prompt, the applicable skills, the task, and the history.
_Avoid_: Prompt building, prompt stuffing

**Skill**:
A house rule the harness injects into the system prompt so the model doesn't have to guess it.
_Avoid_: Instruction, guideline, plugin

**Task**:
The request given to the model at the start of a run, stating what to build.
_Avoid_: Goal, prompt

### Acting in the world

**Tool**:
A capability the harness will actually perform on the model's behalf, such as writing a file.
_Avoid_: Function, action, plugin

**Tool schema**:
The description of the tools the model is allowed to request: names, purposes, and argument shapes.
_Avoid_: Tool definition, function spec

**Tool contract**:
The pairing of the tools the harness will run with the tool schema the model sees; the two must be kept in step.
_Avoid_: Tool registry, API

**Tool call**:
The model's request that the harness run a named tool with given arguments.
_Avoid_: Action, function call, command

**Tool result**:
The text the harness returns to the model after a tool call, including errors, which are returned as text rather than raised.
_Avoid_: Output, response, observation

**Workspace**:
The scratch directory where the model's files live and the tests run.
_Avoid_: Sandbox, project folder, repo

### Checking the work

**Spec**:
The test suite that defines what "done" means; the harness runs it rather than asking the model about it.
_Avoid_: Requirements, tests (when meaning the definition of done)

**Claim**:
The model's statement that it has finished, which the harness treats as unproven.
_Avoid_: Answer, result, completion

**Evidence**:
The outcome of actually running the spec (exit code and output), which settles whether a claim is true.
_Avoid_: Proof, confidence, feedback

**Verification**:
Running the spec to turn a claim into evidence before accepting the work.
_Avoid_: Validation, review, self-check

**Test failure**:
The evidence of a failed verification, fed back into the history so the model can fix the problem on the next step.
_Avoid_: Error, rejection

### Keeping the context in bounds

**Budget**:
The size limit on the history; when the history grows past it, compaction fires.
_Avoid_: Context window, token limit

**Compaction**:
Replacing the history with a shorter summary that keeps the objective, the approaches ruled out and why, and the paths of files already on disk.
_Avoid_: Truncation, memory, summarization (as the name of the step)

**Step limit**:
The maximum number of steps before the harness stops the run unverified.
_Avoid_: Timeout, max iterations

### Driving the harness in this app

**Scripted model**:
A stand-in for the model that replays a fixed list of replies, one per step, regardless of the context it is shown.
_Avoid_: Mock, fake LLM, simulation

**Live model**:
A real hosted model called over its API, as in the notebook.
_Avoid_: Real mode, online model

**Scenario**:
A named script for the scripted model, written to make one particular harness path fire.
_Avoid_: Test case, demo, example
