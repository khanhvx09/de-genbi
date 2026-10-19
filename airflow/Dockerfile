FROM apache/airflow:3.2.2

# Needed to run the Spark driver JVM when SparkSubmitOperator does
# spark-submit --deploy-mode client against the spark-master standalone
# cluster (see spark_jobs DAGs). Must be on PATH before switching to the
# airflow user.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# dbt is installed into its own venv, isolated from Airflow's Python
# environment, so dbt-core's dependency pins can't conflict with Airflow's.
RUN python -m venv /opt/airflow/dbt_venv \
    && /opt/airflow/dbt_venv/bin/pip install --no-cache-dir \
        dbt-core \
        dbt-spark \
        dbt-trino \
        dbt-databricks

RUN pip install --no-cache-dir \
    astronomer-cosmos \
    apache-airflow-providers-fab \
    apache-airflow-providers-apache-spark \
    apache-airflow-providers-databricks \
    pyspark==4.1.1 \
    pyspark-client==4.1.1 \
    databricks-sql-connector \
    trino \
    boto3 \
    kagglehub \
    openai \
    python-dotenv