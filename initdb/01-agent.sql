-- Agent's LangGraph checkpointer/store DB, sharing the metastore-db server.
-- Runs only on first start (empty volume); for an existing volume run it once by hand:
--   docker exec -i metastore-db psql -U hive -d hive < initdb/01-agent.sql
CREATE USER agent WITH PASSWORD 'agent';
CREATE DATABASE agent OWNER agent;
