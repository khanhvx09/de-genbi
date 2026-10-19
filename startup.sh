#!/bin/bash

source "$HOME/.cargo/env"

export PYSPARK_DRIVER_PYTHON=jupyter
export PYSPARK_DRIVER_PYTHON_OPTS='lab --ip=0.0.0.0'
export DELTA_PACKAGE_VERSION=delta-spark_4.1_2.13:4.3.1
export HADOOP_AWS_PACKAGE_VERSION=org.apache.hadoop:hadoop-aws:3.4.1
export HIVE_METASTORE_URIS=thrift://hive-metastore:9083

# The base image's PIP_INDEX_URL points at an internal Databricks proxy that
# isn't reachable from here; override it with public PyPI for this install.
PIP_INDEX_URL=https://pypi.org/simple python3 -m pip install --user -r /opt/requirements.txt

# This container doubles as the Spark standalone master; start it in the
# background before launching the driver/Jupyter process in the foreground.
$SPARK_HOME/bin/spark-class org.apache.spark.deploy.master.Master --host spark-master &
until bash -c "echo > /dev/tcp/spark-master/7077" 2>/dev/null; do
  sleep 1
done

$SPARK_HOME/bin/pyspark --master spark://spark-master:7077 \
  --packages io.delta:${DELTA_PACKAGE_VERSION},${HADOOP_AWS_PACKAGE_VERSION} \
  --conf "spark.driver.host=spark-master" \
  --conf "spark.driver.extraJavaOptions=-Divy.cache.dir=/tmp -Divy.home=/tmp -Dio.netty.tryReflectionSetAccessible=true" \
  --conf "spark.sql.extensions=io.delta.sql.DeltaSparkSessionExtension" \
  --conf "spark.sql.catalog.spark_catalog=org.apache.spark.sql.delta.catalog.DeltaCatalog" \
  --conf "spark.sql.catalogImplementation=hive" \
  --conf "spark.sql.session.timeZone=Asia/Singapore" \
  --conf "spark.hadoop.hive.metastore.uris=${HIVE_METASTORE_URIS}" \
  --conf "spark.hadoop.hive.metastore.schema.verification=false"