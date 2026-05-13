import json
import logging
import os
import functions_framework

from google.cloud import bigquery, storage


logging.basicConfig(level=logging.INFO)

BQ_PROJECT = os.environ["BQ_PROJECT"]
BQ_DATASET = os.environ["BQ_DATASET"]
BQ_TABLE = os.environ["BQ_TABLE"]

SCHEMA = [
    bigquery.SchemaField("city", "STRING"),
    bigquery.SchemaField("latitude", "FLOAT"),
    bigquery.SchemaField("longitude", "FLOAT"),
    bigquery.SchemaField("timestamp", "TIMESTAMP"),
    bigquery.SchemaField("temperature_celsius", "FLOAT"),
    bigquery.SchemaField("relative_humidity_pct", "FLOAT"),
    bigquery.SchemaField("wind_speed_kmh", "FLOAT"),
    bigquery.SchemaField("precipitation_mm", "FLOAT"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP"),
]


def ensure_table(client: bigquery.Client, table_ref: str):
    """Create the BigQuery table if it doesn't exist yet."""
    try:
        client.get_table(table_ref)
    except Exception:
        table = bigquery.Table(table_ref, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(field="timestamp")
        client.create_table(table)
        logging.info("Created BigQuery table %s", table_ref)


def load_ndjson_from_gcs(bucket_name: str, blob_name: str) -> list[dict]:
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        content = blob.download_as_text()
        logging.info("Downloaded gs://%s/%s", bucket_name, blob_name)
    except Exception as e:
        logging.error("Failed to download from GCS: %s", str(e))
        raise

    return [json.loads(line) for line in content.splitlines() if line.strip()]


@functions_framework.cloud_event
def load(cloud_event):
    """GCS-triggered Cloud Run Function: load a JSON file from GCS into BigQuery."""
    data = cloud_event.data
    bucket_name = data["bucket"]
    blob_name = data["name"]

    if not blob_name.startswith("weather/"):
        logging.info("Skipping %s — not in weather/ prefix", blob_name)
        return

    logging.info("Processing gs://%s/%s", bucket_name, blob_name)

    records = load_ndjson_from_gcs(bucket_name, blob_name)
    if not records:
        logging.info("File is empty, nothing to load.")
        return

    try:
        bq = bigquery.Client(project=BQ_PROJECT)
        table_ref = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
        ensure_table(bq, table_ref)

        errors = bq.insert_rows_json(table_ref, records)
        if errors:
            logging.error("BigQuery insert errors: %s", errors)
            raise RuntimeError(f"BigQuery insert errors: {errors}")

        logging.info("Inserted %d rows into %s", len(records), table_ref)
    except Exception as e:
        logging.error("Failed to load into BigQuery: %s", str(e))
        raise
