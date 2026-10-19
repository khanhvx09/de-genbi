# sale — dbt on Trino

| Layer  | Relation                                   | Tạo bởi                                   |
|--------|--------------------------------------------|-------------------------------------------|
| bronze | `hive.bronze.superstore_raw` (external, CSV trên `s3://lakehouse/raw/superstore`) | macro `create_bronze` (on-run-start) |
| silver | `delta.silver.superstore_orders`            | `models/silver/`                          |
| gold   | `delta.gold.sales`                          | `models/gold/` — Cube đọc trực tiếp       |

Hai catalog Trino, cùng dùng một Hive Metastore:
- `hive` (`trino/catalog/hive.properties`, Hive connector): chỉ cho bronze, vì CSV external table chỉ Hive connector tạo được (var `bronze_catalog`).
- `delta` (`trino/catalog/delta.properties`, Delta Lake): catalog mặc định trong `profiles.yml`, dbt ghi silver/gold vào đây.
Spark thấy đúng tên schema `bronze` / `silver` / `gold`.
Tên schema = đúng giá trị `+schema` (macro `generate_schema_name`), không ghép thêm prefix target.

## Chạy từ host

```bash
cd airflow/dbt/sale
export DBT_TARGET=dev DBT_PROFILES_DIR=.
dbt deps
dbt build                       # bronze table + silver + gold + tests
dbt build -s tag:gold           # chỉ gold
```

Trong Airflow: DAG `superstore_etl`, task `dbt_build_silver_gold`.
