"""Agent Framework weather runtime instrumented with Microsoft OpenTelemetry.

This runtime is hosted outside Foundry. Foundry stores the external-agent
registration and reads the spans emitted by this process.

Agent Framework's native instrumentation emits the GenAI spans. The Microsoft
OpenTelemetry distro exports them to the Application Insights resource
connected to the Foundry project.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=True)
os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "SPAN_AND_EVENT")
os.environ.setdefault("ENABLE_INSTRUMENTATION", "true")
os.environ.setdefault("ENABLE_SENSITIVE_DATA", "true")

# Configure OpenTelemetry before importing instrumented libraries.
from microsoft.opentelemetry import use_microsoft_opentelemetry  # type: ignore

AGENT_NAME = os.environ.get("AGENT_NAME", "weather-agent-framework")
AGENT_ID = f"{AGENT_NAME}-v1"

use_microsoft_opentelemetry(
    enable_azure_monitor=True,
    azure_monitor_connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"],
    sampling_ratio=1.0,
    instrumentation_options={
        "fastapi": {"enabled": False},
    },
)

from agent_framework import Agent, AgentSession, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import enable_sensitive_telemetry
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI, Request
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import BaseModel

enable_sensitive_telemetry()


@tool(approval_mode="never_require")
def get_current_weather(city: str) -> str:
    """Return the current weather for the given city.

    This is a stub that returns deterministic fake data so the sample is
    runnable without a third-party weather API key.
    """
    fake = {
        "seattle": "59F and raining",
        "new york": "72F and partly cloudy",
        "tokyo": "68F and clear",
        "london": "55F and overcast",
    }
    return fake.get(city.lower(), f"70F and sunny in {city}")


@tool(approval_mode="never_require")
def get_forecast(city: str, days: int = 3) -> str:
    """Return a short multi-day forecast for the given city."""
    return f"{days}-day forecast for {city}: mild temperatures, occasional showers."


def build_agent(credential: DefaultAzureCredential) -> Agent:
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        credential=credential,
    )
    return Agent(
        client=client,
        id=AGENT_ID,
        name=AGENT_NAME,
        instructions=(
            "You are a helpful weather assistant. Use the provided tools to "
            "answer questions about current weather and short-term forecasts. "
            "Be concise."
        ),
        tools=[get_current_weather, get_forecast],
        default_options={"store": False},
    )


class AskRequest(BaseModel):
    question: str


class ChatRequest(BaseModel):
    thread_id: str
    question: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    with DefaultAzureCredential() as credential:
        app.state.agent = build_agent(credential)
        app.state.sessions = {}
        yield


app = FastAPI(title=AGENT_NAME, lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/ask")
async def ask(req: AskRequest):
    agent = app.state.agent
    response = await agent.run(req.question)
    return {"agent": AGENT_NAME, "answer": response.text}


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    """Multi-turn endpoint.

    Turns are grouped into a single distributed trace via the W3C
    ``traceparent`` header supplied by the caller, so every turn of a
    conversation shares one ``trace_id``. The thread id is additionally
    used as the Agent Framework session id.
    """
    agent = app.state.agent
    session = app.state.sessions.setdefault(
        req.thread_id,
        AgentSession(session_id=req.thread_id),
    )

    # Continue the caller's trace when a traceparent is present.
    ctx = TraceContextTextMapPropagator().extract(dict(request.headers))
    token = None
    if trace.get_current_span(ctx).get_span_context().is_valid:
        token = otel_context.attach(ctx)
    try:
        response = await agent.run(req.question, session=session)
    finally:
        if token is not None:
            otel_context.detach(token)

    return {
        "agent": AGENT_NAME,
        "thread_id": req.thread_id,
        "answer": response.text,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "weather_agent:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
