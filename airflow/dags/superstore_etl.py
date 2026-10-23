"""
DAG: Kaggle Superstore CSV -> raw on RustFS (bronze) -> dbt (Trino) silver/gold Delta Lake.
Cube refreshes pre-aggregations on its own via refresh_key, no separate task needed.

  bronze : s3://<bucket>/raw/superstore/superstore.csv, dbt reads it through the external table hive.bronze.superstore_raw
  silver : delta.silver.superstore_orders
  gold   : delta.gold.sales

dbt project: airflow/dbt/sale (mounted at /opt/airflow/dbt/sale), dbt lives in its own venv /opt/airflow/dbt_venv.
"""
from __future__ import annotations

import json
import os

import pendulum
from airflow import DAG
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import PythonOperator

from download_superstore import download_to_s3

BUCKET = os.getenv("LAKE_BUCKET", "lakehouse")
RAW_PREFIX = "raw/superstore"

DBT_BIN = os.getenv("DBT_BIN", "/opt/airflow/dbt_venv/bin/dbt")
DBT_PROJECT_DIR = os.getenv("DBT_PROJECT_DIR", "/opt/airflow/dbt/sale")
DBT_VARS = json.dumps({
    "lake_root": f"s3://{BUCKET}",
    "raw_superstore_location": f"s3://{BUCKET}/{RAW_PREFIX}",
})
DBT_ENV = {
    "DBT_TARGET": "docker",
    "DBT_PROFILES_DIR": DBT_PROJECT_DIR,
    # target/ and logs/ go to /tmp so nothing is written into the host-mounted directory
    "DBT_TARGET_PATH": "/tmp/dbt/sale/target",
    "DBT_LOG_PATH": "/tmp/dbt/sale/logs",
}

with DAG(
    dag_id="superstore_etl",
    start_date=pendulum.datetime(2026, 10, 1, tz="Asia/Singapore"),
    schedule=None,              # static dataset -> manual trigger
    catchup=False,
    tags=["superstore", "llm-analytics", "dbt"],
) as dag:
    download = PythonOperator(
        task_id="download_superstore_to_s3",
        python_callable=download_to_s3,
        op_kwargs={"bucket": BUCKET, "prefix": RAW_PREFIX},
    )
    # build = run + test in dbt's DAG order; on-run-start creates the bronze external table
    dbt_build = BashOperator(
        task_id="dbt_build_silver_gold",
        bash_command=(
            f"cd {DBT_PROJECT_DIR} && "
            f"{DBT_BIN} deps && "
            f"{DBT_BIN} build --vars '{DBT_VARS}'"
        ),
        env=DBT_ENV,
        append_env=True,
    )

    download >> dbt_build
