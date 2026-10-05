# External Agent Observability — Agent Framework Weather Agent

*Microsoft Agent Framework version of the
[external-agent observability sample](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/external-agents/observability).*

This sample shows the **end-to-end story for a Foundry "external" agent**:
a third-party agent runtime that lives **outside** Foundry, registered
into Foundry purely so its OpenTelemetry traces and Foundry-side
evaluations light up in the portal.

The runtime here is a tiny
[Microsoft Agent Framework](https://learn.microsoft.com/agent-framework/overview/agent-framework-overview)
weather agent, instrumented with the
[Microsoft OpenTelemetry distro](https://github.com/microsoft/opentelemetry-distro-python)
so its spans flow into the Application Insights connected to your
Foundry project. The sample runs the agent locally to keep the demo
small. You can deploy the same runtime anywhere you host your agents;
just keep the same environment variables and `gen_ai.agent.id` value.

**Preview note.** External agents are gated behind
`Foundry-Features: ExternalAgents=V1Preview` while in public preview.
The SDK calls below opt in via `allow_preview=True`.

**Instrumentation note.** Agent Framework emits OpenTelemetry GenAI spans
natively when `ENABLE_INSTRUMENTATION=true`. The runtime constructs the
framework agent with the same `id` and `name` used by the external-agent
registration, so `gen_ai.agent.id` resolves to
`weather-agent-framework-v1`.

## Microsoft OpenTelemetry distro — references

To learn more about the distro or to find samples in another language,
start here:

- **Docs:** [Microsoft OpenTelemetry overview](https://learn.microsoft.com/en-us/azure/microsoft-opentelemetry/overview)
- **Agent Framework observability:** [Observability](https://learn.microsoft.com/agent-framework/agents/observability)
- **Samples by language:**
  - .NET — [microsoft/opentelemetry-distro-dotnet](https://github.com/microsoft/opentelemetry-distro-dotnet)
  - Python — [microsoft/opentelemetry-distro-python](https://github.com/microsoft/opentelemetry-distro-python)
  - JavaScript — [microsoft/opentelemetry-distro-javascript](https://github.com/microsoft/opentelemetry-distro-javascript)

## What's in this folder

| File | Purpose |
| --- | --- |
| [weather_agent.py](weather_agent.py) | Agent Framework weather agent + Microsoft OTel distro, exposed as a FastAPI HTTP service. This is the "external runtime". |
| [.env.example](.env.example) | Placeholder environment template for local configuration. |
| [generate_traffic.py](generate_traffic.py) | Sends a handful of weather questions to the running agent. |
| [generate_multiturn_traffic.py](generate_multiturn_traffic.py) | Drives multi-turn conversations, propagating one W3C `traceparent` per conversation. |
| [register_external_agent.py](register_external_agent.py) | Registers the runtime in Foundry as `kind=external` via the `azure-ai-projects` SDK. |
| [run_trace_eval.py](run_trace_eval.py) | Runs a one-off trace-based eval over the registered agent and prints scores. |
| [run_multiturn_trace_eval.py](run_multiturn_trace_eval.py) | Runs a conversation-level (multi-turn) trace eval and prints per-conversation scores. |
| [schedule_multiturn_trace_eval.py](schedule_multiturn_trace_eval.py) | Creates/lists/deletes a Foundry schedule that re-runs the multi-turn trace eval on a cron cadence. |
| [requirements.txt](requirements.txt) | Python deps for both the runtime and the helper scripts. |

## Architecture

```text
   ┌──────────────────────────┐       OTel spans         ┌──────────────────────┐
   │ Local weather agent      │ ───────────────────────▶ │ Application Insights │
   │ Agent Framework + distro │  gen_ai.agent.id =       │ (linked to project)  │
   └──────────────────────────┘  "weather-agent-         └─────────┬────────────┘
                                 framework-v1"                      │
                                                                    │
                              register_external_agent.py            │ trace view
                                       │                            ▼
                                       ▼                     ┌─────────────────────┐
                              ┌─────────────────────┐        │   Foundry Portal    │
                              │  Foundry Project    │ ◀────  │  Agents → traces    │
                              │  agent kind=external│        │  Evaluations        │
                              └─────────────────────┘        └─────────────────────┘
```

## Prerequisites

1. **Azure resources**
   - A Foundry project with an Application Insights connection.
   - A model deployment (for example, `gpt-5.4-mini`) in that project for both
     the agent LLM and the eval judge.
2. **Permissions**
   - `Foundry User` on the Foundry project for the identity that runs the
     local weather agent and registration/evaluation scripts.
   - `Foundry User` on the parent Foundry resource for the project managed
     identity. Account scope is required because scheduled evaluations invoke
     the evaluator model deployment.
   - For trace evaluation, the Foundry project managed identity needs
     **Reader** *and* **Privileged Monitoring Data Reader** on the connected
     Application Insights (the latter is required to read GenAI message
     content — see Step 5).
3. **Local authentication**
   - Install the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
     and sign in with `az login`. If you use multiple tenants, specify the
     tenant with `az login --tenant <tenant-id>`.

## Step 1 — Configure environment

Start from [.env.example](.env.example), create a local `.env`, and
fill in your project, Application Insights, and model deployment values. The
Python scripts load this file automatically, and the local `.env` file is
ignored by git. Authentication is keyless: `DefaultAzureCredential` uses your
Azure CLI identity during local development.

```env
FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...
AZURE_OPENAI_DEPLOYMENT=gpt-5.4-mini
AGENT_NAME=weather-agent-framework
# Optional. Only needed by run_multiturn_trace_eval.py --trace-id-mode.
APPINSIGHTS_RESOURCE_ID=/subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.Insights/components/<appinsights-name>
```

`FoundryChatClient` resolves the model through the project endpoint and uses
Entra ID, so this sample does not need an API key.

The runtime sets the required OpenTelemetry defaults before instrumentation and
explicitly calls `enable_sensitive_telemetry()` so trace evaluations can read
input and output messages. Review this setting in
[weather_agent.py](weather_agent.py) before using the sample with sensitive
prompts or responses.

For an Azure-hosted deployment, use a managed identity with the same
`Foundry User` role and replace `DefaultAzureCredential` with
`ManagedIdentityCredential` so production authentication is deterministic.

## Step 2 — Run the external runtime locally

```bash
cd samples/python/external-agents/observability-agent-framework
python -m venv .venv
# Activate .venv for your shell.
python -m pip install -r requirements.txt
python weather_agent.py
```

In another terminal, verify the runtime is healthy:

```bash
python -c "import httpx; print(httpx.get('http://localhost:8000/healthz').json())"
```

## Step 3 — Generate local traffic

```bash
python generate_traffic.py http://localhost:8000
```

Wait a minute or two for OpenTelemetry export and Application Insights
ingestion. The agent spans should include
`gen_ai.agent.id = weather-agent-framework-v1`, `gen_ai.input.messages`, and
`gen_ai.output.messages`.

## Step 4 — Register the external agent in Foundry

```bash
python register_external_agent.py
```

This calls `project_client.agents.create_version(...)` with an
`ExternalAgentDefinition`, which creates the Foundry agent record if it
does not already exist. After registration succeeds, open the Foundry
portal:

> **Project → Agents → `weather-agent-framework` → Traces**

The trace view will show spans attributed to this `external` agent.

## Step 5 — Run a one-off trace evaluation

Before running the trace evaluation, grant the Foundry project managed
identity **two** roles on the connected Application Insights resource:

- **Reader** — to authorize the resource-context trace query.
- **Privileged Monitoring Data Reader** — to read the GenAI **message content**
  (`gen_ai.input.messages` / `gen_ai.output.messages`). Depending on your
  Application Insights, this content may live in a separate `genAIContent`
  table that Reader alone cannot read. Without this role the
  evaluation can reject every trace because no supported input/output message
  content remains after filtering.

```bash
python run_trace_eval.py
```

This:

1. Creates an OpenAI-compatible eval group with the built-in trace
   evaluator `intent_resolution`.
2. Creates an `azure_ai_trace_data_source_preview` `agent_filter` run scoped
   to that agent over the last 24 hours.
3. Polls until completion and prints per-criterion pass/fail counts.

One-off runs appear on the project-wide **Optimize → Evaluations** page. The
agent's **Evaluation → Automatic Evaluation** tab lists recurring evaluation
configurations, not individual one-off runs. Populate that tab by creating a
scheduled or continuous evaluation. External agents only emit OpenTelemetry
traces, so use a scheduled trace evaluation; a continuous rule triggered by
`responseCompleted` does not fire for this runtime.

## Step 6 — Evaluate multi-turn conversations

The steps above score a single turn at a time. To evaluate whole
conversations, the runtime needs to (a) carry state across turns and
(b) emit every turn of a conversation into the *same* trace.

### How turns are grouped

Grouping uses the W3C [trace context](https://www.w3.org/TR/trace-context/)
standard, not an application-level id:

* [generate_multiturn_traffic.py](generate_multiturn_traffic.py) opens one
  root span per conversation and injects that span's `traceparent` header
  into every turn's HTTP request.
* The `/chat` endpoint in [weather_agent.py](weather_agent.py) extracts the
  inbound `traceparent` and attaches it before invoking the agent.

Every turn therefore shares one `trace_id`, so **one trace is one
conversation**. `/chat` additionally creates an Agent Framework
`AgentSession` whose `session_id` is the request's thread id, preserving
conversation history across turns.

Generate the traffic:

```bash
python generate_multiturn_traffic.py http://localhost:8000
```

### Run the conversation-level evaluation

```bash
python run_multiturn_trace_eval.py
```

By default, the script deletes its temporary evaluation definition when the run
finishes. Add `--no-cleanup` to preserve it for portal inspection or SDK
troubleshooting:

```bash
python run_multiturn_trace_eval.py --no-cleanup
```

The request differs from the single-turn eval in two ways — the
`azure_ai_trace_data_source_preview` `agent_filter` data source (the older
`azure_ai_traces` source is being deprecated in favor of it) and the
`evaluation_level` field on the run:

```python
data_source={
    "type": "azure_ai_trace_data_source_preview",
    "trace_source": {
        "type": "agent_filter",
        "agent_name": AGENT_NAME,   # filter by the registered agent
        "start_time": start_unix,   # Unix seconds
        "end_time": end_unix,       # Unix seconds (padded for ingestion lag)
        "max_traces": 50,
    },
},
extra_body={"evaluation_level": "conversation"},
```

Two consequences follow from that flag:

* Testing criteria map to the whole conversation, `{"messages":
  "{{item.messages}}"}`, rather than per-turn `{{item.query}}` /
  `{{item.response}}`.
* The criteria are the conversation-level built-ins —
  `customer_satisfaction`, `task_completion`, `coherence`, and
  `groundedness` — configured with `initialization_parameters={"model": ...}`.

The run emits one output item per conversation, each carrying the
`conversation_id`, `trace_id`, contributing `span_ids`, and the full
reconstructed `messages` array.

### Selecting conversations explicitly

`--trace-id-mode` switches to the `trace_id_source` shape, which resolves
trace ids from Application Insights client-side and passes them explicitly:

```bash
python run_multiturn_trace_eval.py --trace-id-mode
```

This mode requires `APPINSIGHTS_RESOURCE_ID`, and — because it queries
Application Insights from your machine — the identity you run it with needs
**Log Analytics Reader** (or **Monitoring Reader**) on that resource. It
produces the same scores, but because the request identifies traces by id
rather than by agent, the resulting run is not associated with the registered
agent in the portal. Prefer the default agent filter unless you need to
evaluate a specific set of traces.

## Step 7 — Schedule repeated evaluation

The scripts above are one-off: each invocation scores the traces in its
lookback window and exits. To repeat an evaluation automatically, let Foundry
run the trace eval on a cadence with a **schedule**.
[schedule_multiturn_trace_eval.py](schedule_multiturn_trace_eval.py) creates one
for you:

```bash
python schedule_multiturn_trace_eval.py                       # hourly
python schedule_multiturn_trace_eval.py --cron "*/30 * * * *" --lookback-hours 1
python schedule_multiturn_trace_eval.py --list                # list schedule runs
python schedule_multiturn_trace_eval.py --delete              # remove the schedule
```

A schedule runs on a timer, so it works for trace-sourced external agents.
(An evaluation *rule* would not: rules trigger on an agent's
`responseCompleted` events, which an external agent that only emits
OpenTelemetry traces never fires.)

Under the hood it creates a persisted eval group, then attaches a schedule whose
task re-runs that eval. The trace window (`start_time`/`end_time`, derived from
`--lookback-hours`) is converted to absolute Unix timestamps when the schedule
is created. Each cron invocation therefore re-evaluates that fixed window; it
does not advance the window to include traces produced later. Delete and
recreate the schedule to select a new window.

```python
from azure.ai.projects.models import Schedule, CronTrigger, EvaluationScheduleTask

# The scheduled run payload mirrors what run_multiturn_trace_eval.py passes to
# client.evals.runs.create in Step 6. Two differences when building it by hand:
# it must carry eval_id, and evaluation_level (sent via extra_body by the OpenAI
# client) is just a top-level key here.
eval_run = {
    "eval_id": eval_object.id,
    "name": "weather-agent-framework-multiturn-scheduled",
    "data_source": {
        "type": "azure_ai_trace_data_source_preview",
        "trace_source": {
            "type": "agent_filter",
            "agent_name": AGENT_NAME,   # filter by the registered agent
            "start_time": start_unix,   # Unix seconds
            "end_time": end_unix,       # Unix seconds (padded for ingestion lag)
            "max_traces": 50,
        },
    },
    "metadata": {"agent_name": AGENT_NAME},
    "evaluation_level": "conversation",
}

project_client.beta.schedules.create_or_update(
    schedule_id=SCHEDULE_ID,
    schedule=Schedule(
        display_name="weather-agent-framework multi-turn conversation eval",
        enabled=True,
        trigger=CronTrigger(expression="0 * * * *", time_zone="UTC"),
        task=EvaluationScheduleTask(eval_id=eval_object.id, eval_run=eval_run),
    ),
)
```

The `eval_run` payload is the same shape passed to `client.evals.runs.create`
in Step 6 (data source, metadata, and the `evaluation_level` flag), so the
scheduled runs score conversations just like the manual run, subject to the
fixed-window limitation above. Inspect runs with `--list` and stop the schedule
with `--delete` (these call `project_client.beta.schedules.list_runs` /
`project_client.beta.schedules.delete`). Schedules are in preview.
