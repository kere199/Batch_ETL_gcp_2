import json
import logging
import os
import functions_framework
import requests

from datetime import datetime, timezone
from google.cloud import storage


logging.basicConfig(level=logging.INFO)

GCS_BUCKET = os.environ["GCS_BUCKET"]
LATITUDE = 13.7563
LONGITUDE = 100.5018
CITY = "Bangkok"


def fetch_weather() -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
        "forecast_days": 1,
        "timezone": "Asia/Bangkok",
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def flatten_records(raw: dict) -> list[dict]:
    hourly = raw["hourly"]
    records = []
    for i, ts in enumerate(hourly["time"]):
        records.append({
            "city": CITY,
            "latitude": raw["latitude"],
            "longitude": raw["longitude"],
            "timestamp": ts,
            "temperature_celsius": hourly["temperature_2m"][i],
            "relative_humidity_pct": hourly["relative_humidity_2m"][i],
            "wind_speed_kmh": hourly["wind_speed_10m"][i],
            "precipitation_mm": hourly["precipitation"][i],
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        })
    return records


def save_to_gcs(records: list[dict]) -> str:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    destination_path = f"weather/{CITY.lower()}_{run_ts}.json"

    # Newline-delimited JSON — BigQuery's preferred batch format
    ndjson = "\n".join(json.dumps(r) for r in records)

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(destination_path)
        blob.upload_from_string(ndjson, content_type="application/json")
        logging.info("Uploaded data to gs://%s/%s", GCS_BUCKET, destination_path)
    except Exception as e:
        logging.error("Failed to upload to GCS: %s", str(e))
        raise

    return destination_path


@functions_framework.http
def extract(request):
    """HTTP-triggered Cloud Run Function: extract weather data and save to GCS."""
    try:
        raw = fetch_weather()
        records = flatten_records(raw)
        destination_path = save_to_gcs(records)
        gcs_uri = f"gs://{GCS_BUCKET}/{destination_path}"
        logging.info("ETL extract complete. %d records saved to %s", len(records), gcs_uri)
        return json.dumps({"status": "success", "gcs_uri": gcs_uri, "records": len(records)}), 200
    except Exception as e:
        logging.error("Extract function failed: %s", str(e))
        return json.dumps({"status": "error", "message": str(e)}), 500
