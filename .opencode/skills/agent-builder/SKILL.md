---
name: agent-builder
description: >-
  Use this skill whenever building a self-looping AI agent powered by MiniMax models (M2.1, M2.5, M2.7) accessed through OpenCode Zen. Triggers include: "tool-calling agent with MiniMax", "agentic loop on Zen", "MiniMax function calling", "OpenCode Zen agent", "MiniMax M2 tool use", or any request to build an autonomous agent that queries APIs and loops until satisfied using MiniMax via the OpenCode gateway. Covers the OpenAI-compatible wire format used by Zen, MiniMax-specific <think> tag and reasoning chain handling, finish_reason: "tool_calls" loop logic, parallel tool execution, error recovery, streaming with reasoning_split, stateful multi-turn conversation history, safe loop termination, prompt caching, verbosity management, and OpenCode Zen-specific gotchas. Also covers official MiniMax inference parameters, prompt engineering best practices, and real-world performance characteristics.
---

# Self-Looping Agent with MiniMax via OpenCode Zen

## Overview

MiniMax M2-series models (M2.1, M2.5, M2.7) are built for agentic, tool-calling workflows.
Accessed via **OpenCode Zen** — OpenCode's curated, benchmarked AI gateway — you get a
tested version of each model at an OpenAI-compatible endpoint.

MiniMax M2.7 delivers roughly 90% of Claude Opus 4.6 quality at about 7% of the cost
(Kilo Code benchmark, 2026). The tradeoff: it is 4× more verbose than average reasoning
models and around 2× slower than the fastest options. This skill covers everything needed
to build production agents on this stack — including the gotchas that benchmarks don't mention.

---

## Stack Summary

| Layer         | Detail                                                     |
|---------------|------------------------------------------------------------|
| Gateway       | OpenCode Zen (`https://opencode.ai/zen/v1`)                |
| Auth          | `Authorization: Bearer <OPENCODE_ZEN_API_KEY>`             |
| Wire format   | OpenAI Chat Completions (`/chat/completions`)              |
| Tool calling  | OpenAI `tools` array + `finish_reason: "tool_calls"`       |
| Reasoning     | MiniMax `<think>` tags / `reasoning_split` param           |
| Best models   | `minimax-m2-7`, `minimax-m2-5`, `minimax-m2-1`             |

---

## OpenCode Zen Setup

### 1. Get your API key
Sign in at https://opencode.ai/auth, add billing details, copy your API key.

### 2. Environment variable
```bash
export OPENCODE_ZEN_API_KEY="sk-..."
```

### 3. Base URL and auth header (every request)
```javascript
const ZEN_BASE = "https://opencode.ai/zen/v1";
// Header: Authorization: Bearer ${process.env.OPENCODE_ZEN_API_KEY}
```

### 4. Model IDs on Zen — use hyphen format, not dots

| Model             | Zen Model ID           | Context    | Notes                                 |
|-------------------|------------------------|------------|---------------------------------------|
| MiniMax M2.7      | `minimax-m2-7`         | 200K       | Latest flagship, best agentic perf    |
| MiniMax M2.5      | `minimax-m2-5`         | 1M tokens  | SOTA coding, 80.2% SWE-Bench Verified |
| MiniMax M2.5 Free | `minimax-m2-5-free`    | 131K out   | Free tier — dev/test only, not prod   |
| MiniMax M2.1      | `minimax-m2-1`         | 1M tokens  | Strong multilingual + reasoning       |

**Critical**: Zen requires hyphens in model IDs. `minimax-m2.7` → HTTP 400. Always use `minimax-m2-7`.

In OpenCode TUI config: `opencode/minimax-m2-7`

---

## Official Inference Parameters

MiniMax publishes specific parameter recommendations for best M2-series performance.
Always set these — the defaults degrade agent quality:

```javascript
body: JSON.stringify({
  model: "minimax-m2-7",
  temperature: 1.0,   // Official: do NOT lower for "consistency"
  top_p: 0.95,        // Official recommendation
  top_k: 40,          // Official recommendation
  max_tokens: 8192,   // 8192–16384 for complex multi-step tasks
  tools: TOOLS,
  tool_choice: "auto",
  extra_body: { reasoning_split: true },
  messages,
})
```

**Why `temperature: 1.0` for an agent?** MiniMax's MoE architecture and interleaved
thinking are tuned for `temperature=1.0`. Lowering it to 0–0.2 (a common instinct for
deterministic tool calling) fights against the internal reasoning process and degrades
tool selection accuracy. The `<think>` chain handles its own structured exploration —
external dampening is counterproductive.

---

## MiniMax-Specific Behaviours You Must Know

### 1. Interleaved `<think>` reasoning blocks

Every M2-series response includes internal chain-of-thought wrapped in `<think>...</think>`
tags. This is the model's reasoning trace — not noise — and must be handled correctly.

**Default output (reasoning inline):**
```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "<think>\nLet me check the sales API first...\n</think>\n\nI'll gather the data now.",
      "tool_calls": [{ "id": "call_abc", "type": "function",
        "function": { "name": "get_sales", "arguments": "{}" } }]
    },
    "finish_reason": "tool_calls"
  }]
}
```

**With `reasoning_split: true` (recommended — separates thinking from content):**
```javascript
extra_body: { reasoning_split: true }
// → message.reasoning_details[0].text  (thinking — for logging/display)
// → message.content                    (clean final text, no <think> tags)
// → message.tool_calls                 (tool invocations if any)
```

### 2. CRITICAL: Preserve the full message object in history

MiniMax documentation states that removing thinking content from multi-turn history
degrades agent performance — the reasoning chain is broken.

When appending the assistant turn, always push the **full raw message object**:

```javascript
// CORRECT
messages.push(response.choices[0].message);

// WRONG — loses tool_calls field and reasoning
messages.push({ role: "assistant", content: response.choices[0].message.content });
```

Strip `<think>` tags for display only — never from the `messages` array.

### 3. `finish_reason` values

| `finish_reason` | Meaning                                  | Action               |
|-----------------|------------------------------------------|----------------------|
| `"tool_calls"`  | Model wants to call one or more tools    | Execute tools, loop  |
| `"stop"`        | Model produced a final text answer       | Return to user       |
| `"length"`      | Response truncated at `max_tokens`       | Increase max_tokens  |

---

## Minimal Working Implementation

### JavaScript / TypeScript

```javascript
const ZEN_BASE = "https://opencode.ai/zen/v1";
const ZEN_KEY  = process.env.OPENCODE_ZEN_API_KEY;
const MODEL    = "minimax-m2-7";
const MAX_ITER = 10;

const TOOLS = [
  {
    type: "function",
    function: {
      name: "get_sales_report",
      description:
        "Fetch sales metrics for a date range. Use for revenue, order count, or growth questions. " +
        "Do NOT use for user metrics — call get_user_metrics for that.",
      parameters: {
        type: "object",
        properties: {
          start_date: { type: "string", description: "ISO date, e.g. 2024-01-01" },
          end_date:   { type: "string", description: "ISO date, e.g. 2024-03-31" },
          region: {
            type: "string",
            enum: ["north", "south", "east", "west"],
            description: "Optional region filter",
          },
        },
        required: ["start_date", "end_date"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "get_user_metrics",
      description: "Return active users, churn rate, and engagement stats for a period.",
      parameters: {
        type: "object",
        properties: {
          period: { type: "string", enum: ["day", "week", "month", "quarter"] },
        },
        required: ["period"],
      },
    },
  },
];

// Replace each case with a real fetch() to your internal APIs
async function executeTool(name, args) {
  switch (name) {
    case "get_sales_report":
      // const res = await fetch(`/api/sales?start=${args.start_date}&end=${args.end_date}`);
      // return res.json();
      return { revenue: 284_300, orders: 1_842, growth_pct: 12.4 };
    case "get_user_metrics":
      return { period: args.period, active_users: 8_421, churn_pct: 2.1 };
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

async function runAgentLoop(userMessage, history = [], systemPrompt = "") {
  const messages = [
    ...(systemPrompt ? [{ role: "system", content: systemPrompt }] : []),
    ...history,
    { role: "user", content: userMessage },
  ];

  for (let i = 0; i < MAX_ITER; i++) {
    const response = await fetch(`${ZEN_BASE}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${ZEN_KEY}`,
      },
      body: JSON.stringify({
        model: MODEL,
        temperature: 1.0,     // Official MiniMax recommendation
        top_p: 0.95,          // Official MiniMax recommendation
        top_k: 40,            // Official MiniMax recommendation
        max_tokens: 8192,
        tools: TOOLS,
        tool_choice: "auto",
        extra_body: { reasoning_split: true },
        messages,
      }),
    });

    if (!response.ok) throw new Error(`Zen API ${response.status}: ${await response.text()}`);

    const data = await response.json();
    const { finish_reason, message } = data.choices[0];

    // CRITICAL: Append FULL message object — preserves <think> and tool_calls
    messages.push(message);

    if (finish_reason === "stop") {
      return { answer: message.content, history: messages };
    }

    if (finish_reason === "tool_calls") {
      // Execute all tool calls in parallel
      const toolResults = await Promise.all(
        (message.tool_calls ?? []).map(async (tc) => {
          const args = JSON.parse(tc.function.arguments);
          try {
            const output = await executeTool(tc.function.name, args);
            return { role: "tool", tool_call_id: tc.id, content: JSON.stringify(output) };
          } catch (err) {
            return { role: "tool", tool_call_id: tc.id, content: JSON.stringify({ error: err.message }) };
          }
        })
      );

      messages.push(...toolResults);
      continue;
    }

    return { answer: message.content ?? "", history: messages };
  }

  throw new Error(`Agent exceeded ${MAX_ITER} iterations without a final answer`);
}
```

### Python (OpenAI SDK → Zen endpoint)

```python
import os, json
from openai import OpenAI

client = OpenAI(
    base_url="https://opencode.ai/zen/v1",
    api_key=os.environ["OPENCODE_ZEN_API_KEY"],
)

MODEL    = "minimax-m2-7"
MAX_ITER = 10

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_sales_report",
            "description": "Fetch sales metrics for a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date":   {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
        },
    }
]

def execute_tool(name: str, args: dict) -> dict:
    if name == "get_sales_report":
        return {"revenue": 284300, "orders": 1842}
    raise ValueError(f"Unknown tool: {name}")

def run_agent_loop(user_message: str, history: list = None, system: str = "") -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})

    for _ in range(MAX_ITER):
        response = client.chat.completions.create(
            model=MODEL,
            temperature=1.0,    # Official MiniMax recommendation
            top_p=0.95,
            max_tokens=8192,
            tools=TOOLS,
            tool_choice="auto",
            extra_body={"reasoning_split": True},
            messages=messages,
        )

        choice  = response.choices[0]
        message = choice.message

        # Append FULL message dict — preserves reasoning chain
        messages.append(message.model_dump())

        if choice.finish_reason == "stop":
            return message.content or ""

        if choice.finish_reason == "tool_calls":
            for tc in (message.tool_calls or []):
                args = json.loads(tc.function.arguments)
                try:
                    result = json.dumps(execute_tool(tc.function.name, args))
                except Exception as e:
                    result = json.dumps({"error": str(e)})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    raise RuntimeError(f"Agent exceeded {MAX_ITER} iterations")
```

---

## Tool Definition Best Practices

Tools use the OpenAI function-calling format. The quality of your descriptions is the
single biggest lever on tool-use accuracy.

```javascript
{
  type: "function",
  function: {
    name: "snake_case_name",    // No spaces, no dots
    description: "...",         // See guidelines below
    parameters: {
      type: "object",
      properties: { ... },
      required: ["..."],
    },
  },
}
```

### Writing Effective Descriptions

| ❌ Weak                               | ✅ Strong                                                                       |
|--------------------------------------|---------------------------------------------------------------------------------|
| "Gets orders"                        | "Retrieves order records. Use for order count, status, or revenue questions."   |
| No return shape                      | "Returns {total, orders[], avg_value}. Each order has id, status, date, total." |
| No disambiguation from similar tools | "Do NOT use for user metrics — call get_user_metrics instead."                  |
| Unconstrained string inputs          | Use `enum` for any value with a known set: `"enum": ["day","week","month"]`     |

### `tool_choice` Options

| Value                                             | Behaviour                                    |
|---------------------------------------------------|----------------------------------------------|
| `"auto"` (default)                                | Model decides — recommended for most agents  |
| `"required"`                                      | Forces at least one tool call per turn       |
| `{ type: "function", function: { name: "X" } }`  | Forces a specific tool — use sparingly       |
| `"none"`                                          | Disables tool calling for this turn          |

---

## Message History Shape

```
[
  { role: "system",    content: "You are a data assistant..." },
  { role: "user",      content: "What were Q1 sales?"          },
  { role: "assistant", content: "<think>...</think>",             ← full raw message
    tool_calls: [{ id: "call_abc", type: "function",               (tool_calls preserved)
      function: { name: "get_sales_report",
        arguments: '{"start_date":"2024-01-01","end_date":"2024-03-31"}' }}] },
  { role: "tool",      tool_call_id: "call_abc",                 ← must match id above
    content: '{"revenue":284300,"orders":1842}' },
  { role: "assistant", content: "In Q1 you had..." },             ← final answer
]
```

**Rules:**
- `tool_call_id` must exactly match the `id` in the preceding `tool_calls` array entry
- The full assistant message must appear before its `tool` result turns
- Never put two consecutive `assistant` turns
- Keep `<think>` content in history — strip for display only

---

## Handling `<think>` Tags for Display

```javascript
// Strip for display only — NEVER strip from the messages array
function displayText(content) {
  return (content ?? "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
}

// With reasoning_split: true, content is already clean
// Show thinking in a collapsible section if useful for debugging:
if (message.reasoning_details?.[0]?.text) {
  console.debug("[Agent thinking]", message.reasoning_details[0].text);
}
```

---

## Verbosity Management — The Most Important Production Concern

MiniMax M2.7 generates **4× more output tokens than the average reasoning model** at
its price tier. Independent evaluation recorded 87M output tokens where the median was
20M. Community users regularly report 16,000+ thinking tokens for simple prompts.

The per-token price ($0.30/M input, $1.10/M output) looks cheap — but the verbosity
tax compounds across every loop iteration and erodes those savings quickly.

### Mitigation strategies

```javascript
// 1. Set a tight max_tokens ceiling — stop runaway generation
max_tokens: 4096,    // Start here; increase only if you see finish_reason: "length"

// 2. Be explicit about output length in the system prompt
// Vague: "keep responses concise"
// Effective: frame it as a technical constraint the reasoning process will respect
"HARD CONSTRAINT: Your final answer must fit in 3 bullet points maximum. " +
"This is a non-negotiable system requirement. Do not include reasoning or caveats."

// 3. Focus on one goal per agent turn — MiniMax docs confirm state tracking
// improves when the model handles limited goals sequentially, not all at once
"Complete one task at a time. Do not attempt to answer multiple questions
in a single turn. Finish the current task, then wait for the next instruction."

// 4. Use tool_choice: "none" for conversational turns with no data requirement
// This skips the tool-selection reasoning overhead entirely
if (isConversationalTurn(userMessage)) {
  requestBody.tool_choice = "none";
}

// 5. For long tasks, include this MiniMax-recommended system prompt addition:
"This is a lengthy task. Keep total input and output tokens within 200k. " +
"Make full use of the context window to complete the task but avoid exhausting tokens."
```

### When verbosity is a feature, not a bug

M2.7's thoroughness is an advantage for:
- Complex multi-file refactoring (it reads system-level dependencies before acting)
- Document intelligence tasks (long outputs improve completeness)
- Batch pipelines and async agents where response time is not user-facing
- Any task where quality matters more than speed

It is a genuine problem for:
- Real-time user-facing chat (45 TPS standard means visible delay)
- Simple conversational turns (model will still reason deeply)
- Tight token budgets where cost matters more than quality depth

---

## Prompt Engineering Best Practices (Official MiniMax)

These are from the official MiniMax M2.7 usage tips documentation.

### 1. Be explicit about output format and content

```
# Less effective
"Create a visualization website"

# More effective
"Create an enterprise-grade data visualization website. Integrate rich analytical
features and interactive functions beyond basic display formats. Include filtering,
drill-down, trend lines, and export functionality."
```

### 2. Explain your intent — tell the model "why"

M2.7 generalises better when it understands the purpose. This is especially important
for output format constraints:

```
# Less effective (model may ignore)
"Do not use markdown formatting"

# More effective (model reasons about why and generalises correctly)
"Your response will be read aloud by a text-to-speech model, so use plain text only —
no markdown symbols, bullet points, headers, or code fences."
```

### 3. Use examples and templates

Show the model a good example and a bad example. M2.7's reasoning process uses these
to generalise rather than just pattern-match:

```
"Write a metric summary following this template:
[Good: Revenue grew 12.4% YoY to $284,300, driven by 1,842 orders (avg $154)]
Avoid vague statements like:
[Bad: Revenue was strong this quarter with good order volume]
Now summarize: {data}"
```

### 4. Scope each agent turn to a limited goal

MiniMax's official guidance: the model has excellent state tracking but it works best
when focusing on **limited goals per turn** rather than processing everything in parallel.
This improves coherence in long-sequence tasks:

```javascript
// Instead of one mega-prompt asking for everything:
"Analyse sales, user growth, inventory levels, and customer churn for Q1–Q3 2024,
 then produce a prioritised action plan with risk assessment."

// Break it into phased turns:
Turn 1: "Fetch and summarise Q1–Q3 sales data."
Turn 2: "Now fetch user and churn metrics for the same period."
Turn 3: "Given what we've collected, produce a prioritised action plan."
```

### 5. System prompt for long tasks (MiniMax official)

When your agent will run many tool call rounds or process large outputs, include this
directly in the system prompt:

```
This is a lengthy multi-step task. Keep total input and output tokens within 200k tokens.
Make full use of the context window to complete the task thoroughly — but do not exhaust
tokens by repeating information already established in earlier turns.
```

---

## Prompt Caching — Zero Configuration, Real Savings

MiniMax on Zen supports **automatic prompt caching**. Cache reads cost $0.06/M tokens
(vs $0.30/M for normal input). For agentic workloads with stable system prompts and
tool definitions re-sent every turn, blended cost can drop to ~$0.06/M.
Zero configuration required — the gateway handles it automatically.

### Structure your messages to maximise cache hits

Caching works on **exact prefix matching**. Put stable content first, dynamic content last:

```javascript
const messages = [
  // ── CACHED ZONE (never changes) ──────────────────────────────
  { role: "system", content: SYSTEM_PROMPT },         // ← cached after first call
  { role: "system", content: TOOL_REFERENCE_DOCS },   // ← also cached if stable

  // ── DYNAMIC ZONE (grows each turn) ───────────────────────────
  ...conversationHistory,
  { role: "user", content: userMessage },
];

// Tools are also cached — keep them stable and ordered
// Do NOT add, remove, or reorder tools between requests in the same session
```

### Cache invalidation — what silently kills your cache hits

These actions invalidate the cache from that point forward:

| Action                                    | Why it breaks cache                              |
|-------------------------------------------|--------------------------------------------------|
| Adding or removing a tool mid-session     | Tool array is part of the cached prefix          |
| Reordering tools between requests         | Prefix byte-mismatch → cache miss                |
| Editing the system prompt                 | Invalidates everything downstream                |
| Switching models mid-session              | Caches are model-specific                        |
| Inserting a message before history        | Shifts all downstream tokens → cache miss        |

**Rule**: Treat everything before `conversationHistory` as immutable once a session starts.
If you need to communicate new context, append it to the next `user` message rather than
editing the system prompt.

### Known cache cap on OpenCode Zen

As of early 2026, there is a known issue where caching via OpenCode Zen caps at approximately
**15,000 tokens**, even for models with 1M context windows. Tokens beyond ~15K are billed
at full input rates regardless.

Practical implications:
- Keep your system prompt + tool definitions under 15K tokens
- Use history summarisation before sessions grow past 15K tokens
- For very large context workflows, consider direct MiniMax API (`api.minimax.io/v1`)

---

## Parallel Tool Execution

When MiniMax returns multiple entries in `message.tool_calls`, run them concurrently:

```javascript
const toolResults = await Promise.all(
  message.tool_calls.map(async (tc) => {
    const args = JSON.parse(tc.function.arguments);
    const output = await executeTool(tc.function.name, args);
    return { role: "tool", tool_call_id: tc.id, content: JSON.stringify(output) };
  })
);
messages.push(...toolResults);
```

If 3 tools each take 400ms — parallel saves 800ms vs sequential per loop iteration.
This matters because M2.7 already adds thinking latency to each round.

---

## Error Handling

### Return errors as tool results so the model adapts

```javascript
try {
  const output = await executeTool(name, args);
  return { role: "tool", tool_call_id: tc.id, content: JSON.stringify(output) };
} catch (err) {
  return { role: "tool", tool_call_id: tc.id, content: JSON.stringify({ error: err.message }) };
}
```

### Per-tool timeout

```javascript
const output = await Promise.race([
  executeTool(name, args),
  new Promise((_, reject) =>
    setTimeout(() => reject(new Error(`${name} timed out`)), 8_000)
  ),
]);
```

### Duplicate call detection

```javascript
const seenCalls = new Set();
for (const tc of toolCalls) {
  const key = `${tc.function.name}:${tc.function.arguments}`;
  if (seenCalls.has(key)) {
    results.push({
      role: "tool", tool_call_id: tc.id,
      content: JSON.stringify({
        error: "Duplicate call detected — this was already called with identical arguments. Try a different approach."
      }),
    });
    continue;
  }
  seenCalls.add(key);
  // normal execution
}
```

---

## Streaming with Reasoning

```javascript
async function streamAgentLoop(userMessage, { onThinking, onToken, onToolCall, onToolResult } = {}) {
  const messages = [{ role: "user", content: userMessage }];

  for (let i = 0; i < MAX_ITER; i++) {
    const response = await fetch(`${ZEN_BASE}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${ZEN_KEY}` },
      body: JSON.stringify({
        model: MODEL, temperature: 1.0, top_p: 0.95, max_tokens: 8192,
        stream: true, tools: TOOLS, extra_body: { reasoning_split: true }, messages,
      }),
    });

    const reader = response.body.getReader();
    const dec = new TextDecoder();
    let buf = "", content = "", finishReason = null;
    const toolCalls = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
        const chunk = JSON.parse(line.slice(6));
        const delta = chunk.choices?.[0]?.delta ?? {};
        finishReason = chunk.choices?.[0]?.finish_reason ?? finishReason;

        if (delta.reasoning_details?.[0]?.text) onThinking?.(delta.reasoning_details[0].text);
        if (delta.content) { content += delta.content; onToken?.(delta.content); }

        for (const tc of delta.tool_calls ?? []) {
          if (!toolCalls[tc.index]) {
            toolCalls[tc.index] = { id: "", type: "function", function: { name: "", arguments: "" } };
            onToolCall?.(tc.function?.name ?? "");
          }
          const t = toolCalls[tc.index];
          t.id += tc.id ?? "";
          t.function.name += tc.function?.name ?? "";
          t.function.arguments += tc.function?.arguments ?? "";
        }
      }
    }

    const assistantMsg = {
      role: "assistant",
      content: content || null,
      ...(toolCalls.length && { tool_calls: toolCalls }),
    };
    messages.push(assistantMsg);

    if (finishReason === "stop") return content;

    if (finishReason === "tool_calls") {
      const results = await Promise.all(
        toolCalls.map(async (tc) => {
          const output = await executeTool(tc.function.name, JSON.parse(tc.function.arguments));
          onToolResult?.(tc.function.name, output);
          return { role: "tool", tool_call_id: tc.id, content: JSON.stringify(output) };
        })
      );
      messages.push(...results);
    }
  }
}
```

---

## Stateful Multi-Turn Chat

```javascript
class MiniMaxAgent {
  constructor(systemPrompt, tools, model = "minimax-m2-7") {
    this.systemPrompt = systemPrompt;
    this.tools = tools;
    this.model = model;
    this.history = [];
  }

  async send(userMessage) {
    const { answer, history } = await runAgentLoop(
      userMessage, this.history, this.systemPrompt
    );
    // Save all turns excluding system — reasoning preserved for MiniMax multi-turn quality
    this.history = history.filter((m) => m.role !== "system");
    return answer;
  }

  reset() { this.history = []; }
}

const agent = new MiniMaxAgent(SYSTEM_PROMPT, TOOLS);
const r1 = await agent.send("What were Q1 2024 sales?");
const r2 = await agent.send("How does that compare to Q2?");  // Full context preserved
```

### Safe History Truncation

Never split a `tool_calls` / `tool` result pair when truncating:

```javascript
function truncateHistory(history, maxTurns = 30) {
  if (history.length <= maxTurns) return history;
  let cut = history.length - maxTurns;
  // Advance past any orphaned tool results to keep pairs intact
  while (cut < history.length && history[cut].role === "tool") cut++;
  return history.slice(cut);
}
```

---

## System Prompt Template

```
You are an internal data assistant with access to company APIs via tool calls.

## Behaviour
- Always call the appropriate tool(s) before answering data questions.
- Call multiple tools in the same turn when their data is independent.
- Chain tool calls across turns when later queries depend on earlier results.
- Stop calling tools as soon as you have enough data to answer completely.
- Only call tools when the data you need is NOT already present in this conversation.
  If information was retrieved earlier in this session, use it directly — do not re-fetch.
- Never answer metric questions from memory — always query the API.

## Output format
- Lead with the most important number or finding.
- Use bullet points for metric lists.
- Format large numbers with commas: 1,234,567.
- State which data sources you queried at the end of each response.
- If a tool returns an error, acknowledge what is missing and answer with what you have.

## Constraints
[Add business rules: "Never expose individual user PII", "Always scope to the user's org_id", etc.]
```

---

## Real-World Performance Characteristics

Use these numbers to set accurate expectations before deploying:

| Metric              | MiniMax Claims        | Independent Measurement (Artificial Analysis) |
|---------------------|-----------------------|------------------------------------------------|
| Standard TPS        | ~60 tokens/sec        | ~45.6 tokens/sec                               |
| HighSpeed TPS       | ~100 tokens/sec       | Not independently verified at same level       |
| Output verbosity    | —                     | 4× median (87M vs 20M tokens in benchmark)     |
| Thinking per turn   | —                     | 16,000+ tokens reported for simple prompts     |
| Quality vs Opus 4.6 | —                     | ~90% quality at ~7% of the cost (Kilo Code)    |

**What this means for agent design:**
- At 45 TPS standard, a 2,000-token thinking block takes ~44 seconds before the first content token
- A 10-round loop with 1,000 thinking tokens per round adds ~222 seconds of latency
- Use HighSpeed variants for user-facing loops; batch/async agents are where M2.7 shines
- Set `MAX_ITER` conservatively (5–8) for standard; verbosity compounds

---

## Model Selection Guide

| Model              | Zen ID              | Best For                                               |
|--------------------|---------------------|--------------------------------------------------------|
| MiniMax M2.7       | `minimax-m2-7`      | Batch / async agents. Complex reasoning. Best quality. |
| MiniMax M2.5       | `minimax-m2-5`      | Coding agents. 80.2% SWE-Bench. 1M context.            |
| MiniMax M2.5 Free  | `minimax-m2-5-free` | Dev and testing only. Zero cost. Not for prod PII.     |
| MiniMax M2.1       | `minimax-m2-1`      | Multilingual. Strong reasoning. Lower cost than M2.7.  |

**Default for production**: `minimax-m2-7` for quality-first agents, `minimax-m2-5` for
coding/latency-sensitive agents.

**Default for development**: `minimax-m2-5-free` (free, but never use with real user data).

---

## Privacy and Data Retention on Zen

| Model                | Data Policy on Zen                                             |
|----------------------|----------------------------------------------------------------|
| `minimax-m2-7`       | Zero-retention — provider does not train on your data         |
| `minimax-m2-5`       | Zero-retention — provider does not train on your data         |
| `minimax-m2-5-free`  | **Data may be used to improve the model during free period**  |
| `minimax-m2-1`       | Zero-retention — provider does not train on your data         |

Never send PII, credentials, or sensitive business data through `minimax-m2-5-free`.

---

## OpenCode Zen Billing Notes

- Zen charges per request and uses a credit balance
- Auto-reload triggers when balance drops below $5 (reloads $20 by default)
- You can disable auto-reload or set a monthly cap per workspace member
- M2.7's verbosity tax means actual spend per task is substantially higher than headline
  per-token rates suggest — monitor real token counts, not just price-per-million

---

## Pre-Ship Checklist

- [ ] `OPENCODE_ZEN_API_KEY` in environment — never hardcoded in source
- [ ] Model ID uses **hyphen format**: `minimax-m2-7` not `minimax-m2.7` (HTTP 400 otherwise)
- [ ] `temperature: 1.0`, `top_p: 0.95`, `top_k: 40` set on every request
- [ ] `MAX_ITER` guard in place (5–8 for standard, 8–15 for HighSpeed async)
- [ ] Full `message` object (including `tool_calls`) appended to history before tool results
- [ ] `<think>` content preserved in history; stripped only for display
- [ ] Each `tool` result's `tool_call_id` exactly matches the corresponding `tool_calls[].id`
- [ ] All tool calls in one turn run in **parallel** with `Promise.all`
- [ ] All `executeTool` errors caught and returned as `tool` role content strings
- [ ] Per-tool timeouts to prevent stalls from slow downstream APIs
- [ ] Duplicate call detection to break potential infinite loops
- [ ] Large tool results (>2K tokens) summarised before returning
- [ ] `reasoning_split: true` set for cleaner content field and loggable thinking
- [ ] History truncation preserves complete `tool_calls`/`tool` result pairs
- [ ] System prompt explains "why" behind every key constraint (not just what)
- [ ] System prompt includes "do not re-fetch data already in context"
- [ ] Static prompt content (system, tool docs) placed first to maximise cache hits
- [ ] Tools not added, removed, or reordered mid-session (cache invalidation)
- [ ] System prompt + tool definitions stay under ~15K tokens (Zen cache cap)
- [ ] `minimax-m2-5-free` not used for any data containing real user information
- [ ] For long tasks: system prompt includes the 200K token budget guidance

---

## Common Errors and Fixes

| Error                                              | Cause                                                     | Fix                                                        |
|----------------------------------------------------|-----------------------------------------------------------|------------------------------------------------------------|
| HTTP 400 from Zen on model selection               | Dot format in model ID (`m2.7`)                           | Use hyphen: `minimax-m2-7`                                 |
| Agent uses wrong tool or ignores tools             | Weak or overlapping tool descriptions                     | Add "Use for X" and "Do NOT use for Y" to each tool        |
| Reasoning quality drops in long conversations      | `<think>` tags stripped from history                      | Preserve raw message objects when appending                |
| `tool_call_id does not match` API error            | Reconstructing assistant message instead of using raw     | Push `response.choices[0].message` directly                |
| Agent exceeds MAX_ITER without answering           | Tool errors causing retries; duplicate calls              | Add logging inside `executeTool`; add duplicate detection  |
| Context window overflow                            | History growing unbounded                                 | Apply `truncateHistory()` before each request              |
| `finish_reason: "length"` truncation               | Response cut off at `max_tokens`                          | Increase `max_tokens` to 8192 or 16384                     |
| Enormous token bills despite cheap per-token price | M2.7 verbosity (4× average output tokens)                 | Set tight `max_tokens`; use length constraints in prompt   |
| Simple prompts trigger 16K+ thinking tokens        | Model reasons deeply on simple tasks                      | Use `tool_choice: "none"` for conversational turns         |
| Agent re-fetches data already in context           | No instruction preventing redundant tool calls            | Add "do not re-fetch data already present" to system prompt|
| Cache hit rate unexpectedly low                    | Tools reordered or system prompt edited mid-session       | Freeze tools/system prompt; append context as user messages|
| Caching stops working past ~15K tokens             | Known Zen/Go cache cap bug (early 2026)                   | Keep system prompt + tools under 15K tokens                |
| Model ignores output length constraints            | `<think>` process overrides brevity instructions          | Frame constraints as "HARD CONSTRAINT: non-negotiable"     |
| Early task termination on long sessions            | M2.7 terminates when approaching context thresholds       | Add 200K token budget hint to system prompt                |
