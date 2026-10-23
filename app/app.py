"""Minimal chat UI: Q&A + table + chart + the Cube query/SQL that was generated."""
import logging
import os
import uuid

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # local run: read OPENAI_API_KEY... from .env (docker already has env_file)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from agent import ask, build_agent, make_memory  # noqa: E402  (sau load_dotenv)

st.set_page_config(page_title="Superstore GenBI", page_icon="📊", layout="wide")


@st.cache_resource
def get_agent():
    checkpointer, store = make_memory()
    return build_agent(checkpointer=checkpointer, store=store)


with st.sidebar:
    st.header("Superstore GenBI")
    user_id = st.text_input("User", value="kevin")
    if "thread_id" not in st.session_state or st.button("New conversation"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.history = []
    st.caption(f"thread: `{st.session_state.thread_id[:8]}`")
    st.markdown("**Suggested questions**\n"
                "- Which region has the highest revenue in 2017?\n"
                "- Plot the monthly revenue trend\n"
                "- Profit margin by category and customer segment\n"
                "- Top 10 most loss-making products")


def short(col: str) -> str:
    return col.split(".", 1)[-1]


def render_result(r: dict, key: str):
    rows = r.get("rows", [])
    if not rows:
        st.info("The query returned no rows.")
        return
    df = pd.DataFrame(rows).rename(columns=short)
    for c in df.columns:  # Cube returns numbers as strings
        try:
            df[c] = pd.to_numeric(df[c])
        except (ValueError, TypeError):
            pass
    chart = r.get("chart", {})
    ys = [short(y) for y in chart.get("y", [])]
    if chart.get("type") == "line":
        x = short(chart["x"])
        df[x] = pd.to_datetime(df[x])
        color = short(chart["color"]) if chart.get("color") else None
        st.plotly_chart(px.line(df.sort_values(x), x=x, y=ys if not color else ys[0], color=color),
                        width="stretch", key=f"{key}-chart")
    elif chart.get("type") == "bar":
        st.plotly_chart(px.bar(df, x=short(chart["x"]), y=ys, barmode="group"),
                        width="stretch", key=f"{key}-chart")
    st.dataframe(df, width="stretch", hide_index=True)
    with st.expander("Cube query / SQL"):
        st.json(r["query"])
        if r.get("sql"):
            st.code(r["sql"], language="sql")


for turn_idx, turn in enumerate(st.session_state.history):
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        for res_idx, r in enumerate(turn.get("results", [])):
            render_result(r, key=f"{st.session_state.thread_id}-{turn_idx}-{res_idx}")

if prompt := st.chat_input("Ask about the data…"):
    st.session_state.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Querying the semantic layer…"):
            try:
                data = ask(get_agent(), prompt, st.session_state.thread_id, user_id)
            except Exception as e:
                data = {"answer": f"⚠️ Agent call failed: {e}", "results": []}
        st.markdown(data["answer"])
        assistant_idx = len(st.session_state.history)  # index the turn will have once appended
        for res_idx, r in enumerate(data.get("results", [])):
            render_result(r, key=f"{st.session_state.thread_id}-{assistant_idx}-{res_idx}")
    st.session_state.history.append({"role": "assistant", "content": data["answer"],
                                     "results": data.get("results", [])})
