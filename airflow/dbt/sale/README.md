# sale — dbt on Trino

| Layer  | Relation                                   | Created by                                |
|--------|--------------------------------------------|-------------------------------------------|
| bronze | `hive.bronze.superstore_raw` (external, CSV on `s3://lakehouse/raw/superstore`) | macro `create_bronze` (on-run-start) |
| silver | `delta.silver.superstore_orders`            | `models/silver/`                          |
| gold   | `delta.gold.sales`                          | `models/gold/` — read directly by Cube    |

Two Trino catalogs, sharing one Hive Metastore:
- `hive` (`trino/catalog/hive.properties`, Hive connector): bronze only, because only the Hive connector can create a CSV external table (var `bronze_catalog`).
- `delta` (`trino/catalog/delta.properties`, Delta Lake): the default catalog in `profiles.yml`; dbt writes silver/gold here.
Spark sees the exact schema names `bronze` / `silver` / `gold`.
Schema name = exactly the `+schema` value (macro `generate_schema_name`), no target prefix is added.

## Run from the host

```bash
cd airflow/dbt/sale
export DBT_TARGET=dev DBT_PROFILES_DIR=.
dbt deps
dbt build                       # bronze table + silver + gold + tests
dbt build -s tag:gold           # gold only
```

Trong Airflow: DAG `superstore_etl`, task `dbt_build_silver_gold`.
