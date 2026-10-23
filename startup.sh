#!/bin/bash

source "$HOME/.cargo/env"

export PYSPARK_DRIVER_PYTHON=jupyter
export PYSPARK_DRIVER_PYTHON_OPTS='lab --ip=0.0.0.0'
export DELTA_PACKAGE_VERSION=delta-spark_4.1_2.13:4.3.1
export HADOOP_AWS_PACKAGE_VERSION=org.apache.hadoop:hadoop-aws:3.4.1
export HIVE_METASTORE_URIS=thrift://hive-metastore:9083
# DataHub Spark agent: Scala 2.13 build is the one that supports Spark 4.
export DATAHUB_SPARK_PACKAGE_VERSION=io.acryl:acryl-spark-lineage_2.13:1.7.0.17

# The base image's PIP_INDEX_URL points at an internal Databricks proxy that
# isn't reachable from here; override it with public PyPI for this install.
PIP_INDEX_URL=https://pypi.org/simple python3 -m pip install --user -r /opt/requirements.txt

# This container doubles as the Spark standalone master; start it in the
# background before launching the driver/Jupyter process in the foreground.
$SPARK_HOME/bin/spark-class org.apache.spark.deploy.master.Master --host spark-master &
until bash -c "echo > /dev/tcp/spark-master/7077" 2>/dev/null; do
  sleep 1
done

# Lineage -> DataHub only when DATAHUB_GMS_URL is set (see docker-compose-datahub.yaml).
# coalesce_jobs=false: the Jupyter session never ends, so emit per query
# instead of waiting for onApplicationEnd.
PACKAGES=io.delta:${DELTA_PACKAGE_VERSION},${HADOOP_AWS_PACKAGE_VERSION}
DATAHUB_CONF=()
if [ -n "${DATAHUB_GMS_URL}" ]; then
  PACKAGES=${PACKAGES},${DATAHUB_SPARK_PACKAGE_VERSION}
  DATAHUB_CONF=(
    --conf "spark.extraListeners=datahub.spark.DatahubSparkListener"
    --conf "spark.datahub.rest.server=${DATAHUB_GMS_URL}"
    # GMS restarts when the Docker VM runs low on memory; don't drop events
    --conf "spark.datahub.rest.max_retries=5"
    --conf "spark.datahub.coalesce_jobs=false"
    --conf "spark.datahub.metadata.include_scheme=false"
    # Without these the datasets exist only as lineage edges and never show
    # up in DataHub search / the Platforms list. materialize builds the
    # dataset + schema, include_schema_metadata actually emits the schema.
    --conf "spark.datahub.metadata.dataset.materialize=true"
    --conf "spark.datahub.metadata.dataset.include_schema_metadata=true"
  )
fi

$SPARK_HOME/bin/pyspark --master spark://spark-master:7077 \
  --packages ${PACKAGES} \
  "${DATAHUB_CONF[@]}" \
  --conf "spark.driver.host=spark-master" \
  --conf "spark.driver.extraJavaOptions=-Divy.cache.dir=/tmp -Divy.home=/tmp -Dio.netty.tryReflectionSetAccessible=true" \
  --conf "spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension" \
  --conf "spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog" \
  --conf "spark.sql.catalogImplementation=hive" \
  --conf "spark.sql.session.timeZone=Asia/Singapore" \
  --conf "spark.hadoop.hive.metastore.uris=${HIVE_METASTORE_URIS}" \
  --conf "spark.hadoop.hive.metastore.schema.verification=false"