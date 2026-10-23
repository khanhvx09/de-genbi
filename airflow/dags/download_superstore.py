"""
Download the Kaggle "Superstore Dataset" (vivek468/superstore-dataset-final) with kagglehub
then push it to RustFS (S3-compatible): s3://<bucket>/raw/superstore/superstore.csv

One CSV file with a header, ~10k order-line rows, 21 columns:
  Row ID, Order ID, Order Date, Ship Date, Ship Mode, Customer ID, Customer Name, Segment,
  Country, City, State, Postal Code, Region, Product ID, Category, Sub-Category, Product Name,
  Sales, Quantity, Discount, Profit
The source file is encoded in Windows-1252 -> converted to UTF-8 before upload so Trino reads it correctly.

Called from the DAG:
  from download_superstore import download_to_s3
  PythonOperator(task_id="download_superstore", python_callable=download_to_s3)

Run by hand (outside Docker, RustFS published on localhost:9000):
  S3_ENDPOINT=http://localhost:9000 python airflow/dags/download_superstore.py

Configured via env: S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION, LAKE_BUCKET.
The dataset is public; if Kaggle asks for login set KAGGLE_USERNAME + KAGGLE_KEY.
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from pathlib import Path

import boto3
import kagglehub
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

DATASET = "vivek468/superstore-dataset-final"
DEFAULT_PREFIX = "raw/superstore"
OBJECT_NAME = "superstore.csv"
SOURCE_ENCODINGS = ("utf-8-sig", "cp1252")


def s3_client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT", "http://rustfs:9000"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY", "rustfsadmin"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY", "rustfsadmin"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
        # RustFS only supports path-style by default (http://host/bucket/key)
        config=Config(s3={"addressing_style": "path"}),
    )


def ensure_bucket(s3: BaseClient, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            raise
        log.info("create bucket %s", bucket)
        s3.create_bucket(Bucket=bucket)


def find_csv(dataset_dir: str) -> Path:
    csvs = sorted(Path(dataset_dir).rglob("*.csv"))
    if len(csvs) != 1:
        raise RuntimeError(f"Expected exactly 1 CSV file in {dataset_dir}, found {len(csvs)}: {csvs}")
    return csvs[0]


def to_utf8(raw: bytes) -> bytes:
    for enc in SOURCE_ENCODINGS:
        try:
            return raw.decode(enc).encode("utf-8")
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Could not decode the file with {SOURCE_ENCODINGS}")


def download_to_s3(bucket: str | None = None, prefix: str = DEFAULT_PREFIX) -> str:
    """
    Download the latest copy from Kaggle (kagglehub local cache) then overwrite s3://<bucket>/<prefix>/superstore.csv.
    Idempotent: re-running only overwrites the same object. Returns the key (to XCom when run in the DAG).
    """
    bucket = bucket or os.getenv("LAKE_BUCKET", "lakehouse")
    key = f"{prefix.strip('/')}/{OBJECT_NAME}"

    dataset_dir = kagglehub.dataset_download(DATASET)
    src = find_csv(dataset_dir)
    log.info("kaggle %s -> %s", DATASET, src)

    s3 = s3_client()
    ensure_bucket(s3, bucket)
    s3.upload_fileobj(io.BytesIO(to_utf8(src.read_bytes())), bucket, key)
    log.info("done -> s3://%s/%s", bucket, key)
    return key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default=None, help="defaults to $LAKE_BUCKET or 'lakehouse'")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        download_to_s3(bucket=args.bucket, prefix=args.prefix)
    except (ClientError, RuntimeError, OSError) as e:
        log.error("error: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
