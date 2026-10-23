# Telco-DE-GenBI — Chat with your data through Cube (semantic layer)

Ask questions about your data in natural language, with conversational memory, and get back **tables + charts**.
Every number goes through the **semantic layer (Cube Core)** — the LLM never writes SQL itself, it only picks
pre-defined measures/dimensions.

Demo dataset: **Kaggle Superstore** (9,994 order lines, 2014–2017, USD).

## 1. Architecture

![Data Pipeline Architecture](demo/Data%20Pipeline%20Architecture.png)

## 2. Components

| Component | Role |
|---|---|
| **RustFS** | S3-compatible object storage (data lake) |
| **Hive Metastore + Postgres** | Table metadata; Postgres also hosts the Airflow and agent databases |
| **Trino** | Query engine; catalog `hive` (bronze), `delta` (silver/gold) |
| **Airflow + dbt** | ETL orchestration, bronze → silver → gold transforms |
| **Cube** | Semantic layer + pre-aggregation |
| **Streamlit app** | Chat UI + LangGraph agent running in a single process |
| **Spark + Jupyter** | Data exploration (`demo/test.ipynb`) |
| **DataHub** | Data catalog + lineage, separate compose file `docker-compose-datahub.yaml` |
| **lineage-relay** | Small proxy (`trino/lineage-relay/relay.py`) between Trino and DataHub, see section 3.3 |

Main directories: `app/` (UI + agent), `cube/model/` (semantic layer), `airflow/` (DAG + dbt),
`trino/` (catalogs, event listener, relay), `spark/`, `evals/`, `initdb/`.

## 3. Logic

### 3.1 Data (medallion)

| Table | Grain | Notes |
|---|---|---|
| `hive.bronze.superstore_raw` | CSV row | external table, all columns `varchar` |
| `delta.silver.superstore_orders` | order line | typed columns, parsed dates, deduplicated by `row_id` |
| `delta.gold.sales` | order line | denormalized + `days_to_ship`; read directly by Cube |

Two catalogs are used because the Delta connector cannot create external CSV tables (bronze → `hive`),
while silver/gold need `CREATE OR REPLACE TABLE` for dbt (→ `delta`).

### 3.2 Agent

1. `search_semantic_layer`: finds the measures/dimensions that fit the question.
2. `lookup_values`: normalizes concrete values (state names, products).
3. `run_query`: sends a structured query (measures, dimensions, time, filters) to Cube; only the `superstore_sales` view is exposed.
4. The UI shows the explanation, a chart (line/bar chosen automatically from the data shape), a table, and the Cube query for verification.
5. Memory: `thread_id` keeps the conversation (follow-up questions work); `save_user_note` / `recall_user_notes` keep terminology per `user_id`.

The LLM is switched via `LLM_MODEL=provider:model` (OpenAI, Anthropic, Azure, Ollama). Quality is measured with
`evals/run_evals.py` against a golden set of required Cube members.

### 3.3 Lineage

- **Spark**: `startup.sh` attaches `acryl-spark-lineage` when `DATAHUB_GMS_URL` is set; it emits per query
  (`coalesce_jobs=false`) and materializes datasets + schemas so tables show up in DataHub search.
  `spark/log4j2.properties` hides the harmless "Query execution is null" listener error log.
- **Trino**: the OpenLineage event listener (`trino/etc/openlineage-event-listener.properties`) only sends queries that write
  data (INSERT/UPDATE/DELETE/MERGE, including CTAS) and skips DDL.
- **lineage-relay**: Trino names jobs after the query id, so DataHub would create one DataFlow + one DataJob per query.
  The relay renames the job to `trino.<target table>` and forwards it to DataHub, so each target table has a single job
  (re-runs overwrite it). Events with no output are dropped.

## 4. Quick start

```bash
cp .env.example .env                                       # fill in OPENAI_API_KEY, CUBEJS_API_SECRET, FERNET_KEY...
docker compose up -d --build                               # data stack + Cube + app (:8501)
docker compose -f docker-compose-airflow.yaml up -d --build  # Airflow (:8090), trigger DAG superstore_etl
docker compose -f docker-compose-datahub.yaml up -d        # optional: DataHub (:9002)
```

> The stack uses a dev configuration (Cube dev mode, Trino without auth) — not for production.
