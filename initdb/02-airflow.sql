-- Airflow metadata DB, sharing the metastore-db server.
-- Runs only on first start (empty volume); for an existing volume run it once by hand:
--   docker exec -i metastore-db psql -U hive -d hive < initdb/02-airflow.sql
CREATE USER airflow WITH PASSWORD 'airflow';
CREATE DATABASE airflow OWNER airflow;
