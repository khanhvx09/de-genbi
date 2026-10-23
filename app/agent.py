"""LangGraph agent: answers data questions through Cube, with short-term (thread) and long-term (user notes) memory.

Runs inside the Streamlit process — `ask()` is the only entry point."""
from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

import cube_client
import semantic_index
from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

MAX_ROWS_TO_LLM = 50
DEFAULT_TOP_K = 10
MAX_TOP_K = 30
DEFAULT_LLM = "openai:gpt-4.1"  # override via env LLM_MODEL, e.g. anthropic:claude-sonnet-5-5
RECURSION_LIMIT = 25

# Query results of the current request -> returned by the API so the UI can draw tables/charts.
current_results: contextvars.ContextVar[list] = contextvars.ContextVar("current_results")


@dataclass
class UserContext:
    user_id: str = "anonymous"


class Filter(BaseModel):
    member: str = Field(description="Full name, e.g. superstore_sales.region")
    operator: Literal["equals", "notEquals", "contains", "notContains", "gt", "gte", "lt", "lte",
                      "set", "notSet", "inDateRange", "beforeDate", "afterDate"]
    values: list[str] = Field(default_factory=list)


class TimeDim(BaseModel):
    dimension: str = Field(description="vd superstore_sales.order_date")
    granularity: Literal["day", "week", "month", "quarter", "year"] | None = None
    date_range: list[str] | None = Field(
        default=None, description='["2017-01-01","2017-12-31"] or null')


def _check_members(names: list[str]) -> list[str]:
    known = cube_client.public_members()
    return [n for n in names if n not in known]


@tool
def search_semantic_layer(query: str, k: int = DEFAULT_TOP_K) -> str:
    """Find the measures and dimensions relevant to the question, with descriptions.
    `query` is a phrase describing what to look for, e.g. "revenue by region"."""
    try:
        docs = semantic_index.search(query, k=min(max(k, 1), MAX_TOP_K))
    except Exception as e:
        logger.exception("search_semantic_layer failed query=%r", query)
        return f"Semantic layer search error: {e}"
    logger.info("search_semantic_layer query=%r hits=%s",
                query, [d.metadata["column_name"] for d in docs])
    return semantic_index.format_docs(docs)


@tool
def lookup_values(dimension: str, contains: str = "", limit: int = 20,
                  runtime: ToolRuntime[UserContext] = None) -> str:
    """Look up the actual values of a string dimension (e.g. region, state, category names) so filters use the exact spelling."""
    if bad := _check_members([dimension]):
        return f"No such member: {bad}. Call search_semantic_layer."
    q: dict = {"dimensions": [dimension], "limit": limit, "order": {dimension: "asc"}}
    if contains:
        q["filters"] = [{"member": dimension, "operator": "contains", "values": [contains]}]
    data = cube_client.load(q, runtime.context.user_id if runtime else "agent")["data"]
    return json.dumps([row[dimension] for row in data], ensure_ascii=False)


@tool
def run_query(measures: list[str],
              dimensions: list[str] | None = None,
              time_dimension: TimeDim | None = None,
              filters: list[Filter] | None = None,
              order: dict[str, Literal["asc", "desc"]] | None = None,
              limit: int = 100,
              runtime: ToolRuntime[UserContext] = None) -> str:
    """Run a query on the semantic layer. Returns the row count and at most the first 50 rows as JSON."""
    dimensions = dimensions or []
    names = list(measures) + dimensions + [f.member for f in (filters or [])]
    if time_dimension:
        names.append(time_dimension.dimension)
    if bad := _check_members(names):
        logger.warning("run_query unknown members: %s", bad)
        return f"No such member: {bad}. Call search_semantic_layer to see the correct names."

    q: dict = {"measures": measures, "dimensions": dimensions, "limit": min(max(limit, 1), 500)}
    if time_dimension:
        td: dict = {"dimension": time_dimension.dimension}
        if time_dimension.granularity:
            td["granularity"] = time_dimension.granularity
        if time_dimension.date_range:
            td["dateRange"] = time_dimension.date_range
        q["timeDimensions"] = [td]
    if filters:
        q["filters"] = [f.model_dump() for f in filters]
    if order:
        q["order"] = order

    user_id = runtime.context.user_id if runtime else "agent"
    logger.info("run_query user=%s query=%s", user_id, json.dumps(q, ensure_ascii=False))
    try:
        res = cube_client.load(q, user_id)
    except Exception as e:  # return the error to the LLM so it can fix the query
        logger.exception("run_query Cube error user=%s", user_id)
        return f"Cube error: {e}"
    rows = res.get("data", [])
    logger.info("run_query rows=%d", len(rows))
    annotation = res.get("annotation", {})
    record = {
        "id": str(uuid.uuid4())[:8],
        "query": q,
        "rows": rows,
        "annotation": annotation,
        "sql": cube_client.to_sql(q, user_id),
    }
    try:
        current_results.get().append(record)
    except LookupError:
        pass
    return json.dumps({"row_count": len(rows), "rows": rows[:MAX_ROWS_TO_LLM],
                       "truncated": len(rows) > MAX_ROWS_TO_LLM}, ensure_ascii=False, default=str)


@tool
def save_user_note(note: str, runtime: ToolRuntime[UserContext]) -> str:
    """Save a long-term user term/preference (e.g. the definition of 'peak hour')."""
    if runtime.store is None:
        return "Long-term memory is not enabled."
    ns = ("users", runtime.context.user_id, "notes")
    runtime.store.put(ns, str(uuid.uuid4()), {"note": note})
    return "Saved."


@tool
def recall_user_notes(runtime: ToolRuntime[UserContext]) -> str:
    """Read the terms/preferences the user saved earlier."""
    if runtime.store is None:
        return "[]"
    items = runtime.store.search(("users", runtime.context.user_id, "notes"), limit=50)
    return json.dumps([i.value["note"] for i in items], ensure_ascii=False)


TOOLS = [search_semantic_layer, lookup_values, run_query, save_user_note, recall_user_notes]


def make_model():
    spec = os.getenv("LLM_MODEL", DEFAULT_LLM)
    provider, _, name = spec.partition(":")
    kwargs: dict = {"temperature": 0}
    if provider == "azure_openai":
        kwargs["azure_deployment"] = name
    if provider == "ollama":
        kwargs["base_url"] = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    return init_chat_model(spec, **kwargs)


def build_agent(model=None, checkpointer=None, store=None):
    return create_agent(
        model or make_model(),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        context_schema=UserContext,
        checkpointer=checkpointer,
        store=store,
    )


def make_memory():
    """(checkpointer, store): Postgres if AGENT_DB_URI is set, otherwise in-memory (lost on restart)."""
    uri = os.getenv("AGENT_DB_URI")
    if not uri:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        return InMemorySaver(), InMemoryStore()
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(uri, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0})
    checkpointer, store = PostgresSaver(pool), PostgresStore(pool)
    checkpointer.setup()
    store.setup()
    return checkpointer, store


def suggest_chart(record: dict) -> dict:
    """Simple heuristic: time series -> line; 1 dimension -> bar; otherwise -> table."""
    q = record["query"]
    measures = q.get("measures", [])
    dims = q.get("dimensions") or []
    td = (q.get("timeDimensions") or [{}])[0]
    if td.get("granularity"):
        x = f"{td['dimension']}.{td['granularity']}"
        if len({row.get(x) for row in record["rows"]}) > 1:  # draw a line only with >= 2 time points
            return {"type": "line", "x": x, "y": measures, "color": dims[0] if dims else None}
    if len(dims) == 1 and measures:
        return {"type": "bar", "x": dims[0], "y": measures}
    return {"type": "table"}


def _text(content) -> str:
    if isinstance(content, list):  # some providers return content blocks
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def ask(agent, message: str, thread_id: str, user_id: str = "anonymous") -> dict:
    """Ask the agent a question. Returns {"answer": str, "results": [query record + chart]}."""
    results: list = []
    token = current_results.set(results)
    started = time.perf_counter()
    logger.info("ask start thread=%s user=%s message=%r", thread_id[:8], user_id, message)
    try:
        out = agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT},
            context=UserContext(user_id=user_id),
        )
    except Exception:
        logger.exception("ask failed thread=%s", thread_id[:8])
        raise
    finally:
        current_results.reset(token)
    logger.info("ask done thread=%s queries=%d elapsed=%.2fs",
                thread_id[:8], len(results), time.perf_counter() - started)
    return {"answer": _text(out["messages"][-1].content),
            "results": [{**r, "chart": suggest_chart(r)} for r in results]}
