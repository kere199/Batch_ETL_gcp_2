# Weather ETL Pipeline on GCP

A batch ETL pipeline built with two Google Cloud Run Functions that extracts hourly weather data, stores it in GCS, and loads it into BigQuery — triggered on a schedule via Cloud Scheduler.

## Architecture

```
Cloud Scheduler (every hour)
        │
        ▼  HTTP trigger
┌───────────────┐        JSON file         ┌─────────────────┐
│   Function 1  │ ──────────────────────►  │   GCS Bucket    │
│   (extract)   │   weather/city_ts.json   │                 │
└───────────────┘                          └────────┬────────┘
                                                    │ GCS finalize event
                                                    ▼
                                           ┌───────────────┐
                                           │  Function 2   │
                                           │    (load)     │
                                           └───────┬───────┘
                                                   │ insert rows
                                                   ▼
                                           ┌───────────────┐
                                           │   BigQuery    │
                                           │ weather_etl   │
                                           │hourly_weather │
                                           └───────────────┘
```

**Data source:** [Open-Meteo](https://open-meteo.com/) — free, no API key required.  
**Data:** Hourly temperature, humidity, wind speed, and precipitation for Bangkok.

---

## Repository Structure

```
├── extract/
│   ├── main.py          # Cloud Run Function 1 — fetch API → save to GCS
│   ├── requirements.txt
│   └── Dockerfile
├── load/
│   ├── main.py          # Cloud Run Function 2 — GCS event → insert to BigQuery
│   ├── requirements.txt
│   └── Dockerfile
├── .github/
│   └── workflows/
│       └── deploy.yml   # CI/CD: auto-deploy both functions on push to main
└── README.md
```

---

## Prerequisites

- GCP project with billing enabled
- APIs enabled: Cloud Functions, Cloud Run, Cloud Build, Cloud Storage, BigQuery, Cloud Scheduler, Pub/Sub, Eventarc
- `gcloud` CLI installed and authenticated

---

## GCP Setup (one-time, manual steps)

### 1. Create a GCS bucket

```bash
gcloud storage buckets create gs://irakli_1 \
  --location=us-central1 \
  --project=gcp-vol2
```

### 2. Create a BigQuery dataset

```bash
bq --location=US mk --dataset gcp-vol2:weather_etl
```

> The BigQuery table (`hourly_weather`) is created automatically by the `load` function on first run.

### 3. Create a Service Account for GitHub Actions

```bash
# Create the service account
gcloud iam service-accounts create github-deploy \
  --display-name="GitHub Actions Deploy" \
  --project=gcp-vol2

# Grant required roles
for ROLE in \
  roles/cloudfunctions.developer \
  roles/run.admin \
  roles/storage.admin \
  roles/bigquery.dataEditor \
  roles/bigquery.jobUser \
  roles/iam.serviceAccountUser \
  roles/eventarc.admin; do
  gcloud projects add-iam-policy-binding gcp-vol2 \
    --member="serviceAccount:github-deploy@gcp-vol2.iam.gserviceaccount.com" \
    --role="$ROLE"
done

# Download the key
gcloud iam service-accounts keys create key.json \
  --iam-account=github-deploy@gcp-vol2.iam.gserviceaccount.com
```

### 4. Add GitHub Actions secrets

In your GitHub repo → **Settings → Secrets and variables → Actions**, add:

| Secret name      | Value                                    |
|------------------|------------------------------------------|
| `GCP_PROJECT_ID` | Your GCP project ID                      |
| `GCP_SA_KEY`     | Full contents of `key.json` (from step 3)|
| `GCS_BUCKET`     | Your GCS bucket name (without `gs://`)   |

> Delete `key.json` from your machine after adding it to GitHub.

### 5. Set up Cloud Scheduler

After the first deployment (step below), get the `extract` function's URL:

```bash
gcloud functions describe extract \
  --gen2 \
  --region=us-central1 \
  --format="value(serviceConfig.uri)"
```

Then create a scheduler job to call it every hour:

```bash
gcloud scheduler jobs create http weather-extract-hourly \
  --location=us-central1 \
  --schedule="0 */12 * * *" \
  --uri=EXTRACT_FUNCTION_URL \
  --http-method=GET \
  --time-zone="Asia/Bangkok"
```

---

## Deployment

Push to the `main` branch — GitHub Actions will automatically deploy both Cloud Run Functions.

```bash
git add .
git commit -m "deploy ETL pipeline"
git push origin main
```

Watch the deployment in the **Actions** tab of your GitHub repository.

---

## Manual Deployment (alternative)

```bash
# Function 1 — extract
gcloud functions deploy extract \
  --gen2 \
  --region=us-central1 \
  --runtime=python312 \
  --source=./extract \
  --entry-point=extract \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET=irakli_1 \
  --project=gcp-vol2

# Function 2 — load
gcloud functions deploy load \
  --gen2 \
  --region=us-central1 \
  --runtime=python312 \
  --source=./load \
  --entry-point=load \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=irakli_1" \
  --set-env-vars BQ_PROJECT=gcp-vol2,BQ_DATASET=weather_etl,BQ_TABLE=hourly_weather \
  --project=gcp-vol2
```

---

## Testing

**Trigger the extract function manually:**

```bash
curl $(gcloud functions describe extract --gen2 --region=us-central1 --format="value(serviceConfig.uri)")
```

**Check GCS for the output file:**

```bash
gcloud storage ls gs://irakli_1/weather/
```

**Query BigQuery:**

```sql
SELECT city, timestamp, temperature_celsius, relative_humidity_pct
FROM `gcp-vol2.weather_etl.hourly_weather`
ORDER BY timestamp DESC
LIMIT 24;
```

---

## BigQuery Schema

| Column | Type | Description |
|---|---|---|
| `city` | STRING | City name |
| `latitude` | FLOAT | Latitude |
| `longitude` | FLOAT | Longitude |
| `timestamp` | TIMESTAMP | Forecast hour (partitioned) |
| `temperature_celsius` | FLOAT | Air temperature at 2m (°C) |
| `relative_humidity_pct` | FLOAT | Relative humidity at 2m (%) |
| `wind_speed_kmh` | FLOAT | Wind speed at 10m (km/h) |
| `precipitation_mm` | FLOAT | Precipitation (mm) |
| `extracted_at` | TIMESTAMP | When the record was extracted |
