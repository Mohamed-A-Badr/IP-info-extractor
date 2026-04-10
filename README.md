# IP Info Extractor

A Django-based web application that performs **batch IP address lookups** using the [ipinfo.io](https://ipinfo.io) API. Submit a list of IPs and get real-time enrichment results streamed back to the browser via WebSockets.

## Features

- Submit a batch of IP addresses through a web UI or REST API
- Asynchronous processing via Celery workers
- Real-time progress updates over WebSockets (Django Channels)
- Auto-generated OpenAPI docs (drf-spectacular)
- Container-based setup with Docker Compose
- Live log monitoring via Dozzle

## Architecture Overview

```
Browser ──POST /api/ips/──► Django (DRF)
                               │
                               ├─► Celery Worker (fetch each IP from ipinfo.io)
                               │         │
                               │         └─► Redis (channel layer) ──► WebSocket ──► Browser
                               │
                               └─► SQLite (batch + IP result records)
```

## Technology Stack

| Layer                  | Technology                                             |
| ---------------------- | ------------------------------------------------------ |
| Web framework          | Django 5.2                                             |
| REST API               | Django REST Framework 3.17 + drf-spectacular (OpenAPI) |
| Async server           | Daphne (ASGI)                                          |
| Real-time              | Django Channels 4 + channels-redis                     |
| Task queue             | Celery 5.6                                             |
| Message broker / cache | Redis 7                                                |
| HTTP client            | httpx                                                  |
| Containerisation       | Docker + Docker Compose                                |
| Log viewer             | Dozzle                                                 |
| Language               | Python 3.11                                            |

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- An [ipinfo.io](https://ipinfo.io) API token (free tier available)

## Getting Started

### 1. Clone the repository

```bash
git clone <repo-url>
cd IP-info-extractor
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
SECRET_KEY=<your-django-secret-key>
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

IP_INFO_API_TOKEN=<your-ipinfo-api-token>
```

> **Note:** When running with Docker Compose the Redis hostname must be `redis` (the service name), not `localhost`.

### 3. Start all services

```bash
docker compose up --build
```

This starts four containers:

| Container       | Purpose                | Port |
| --------------- | ---------------------- | ---- |
| `backend`       | Django + Daphne (ASGI) | 8000 |
| `celery-worker` | Celery task worker     | —    |
| `redis`         | Broker + channel layer | 6379 |
| `dozzle-logs`   | Live log viewer UI     | 8080 |

### 4. Apply database migrations

In a separate terminal (while the containers are running):

```bash
docker compose exec backend python manage.py migrate
```

### 5. Open the application

| URL                                          | Description                      |
| -------------------------------------------- | -------------------------------- |
| http://localhost:8000                        | Web UI — batch list & submission |
| http://localhost:8000/api/schema/swagger-ui/ | Swagger / OpenAPI docs           |
| http://localhost:8080                        | Dozzle log viewer                |

## API Reference

### Submit a batch

```
POST /api/ips/
Content-Type: application/json

{
  "ips": ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
}
```

Response includes a `batch_id` UUID used to track progress.

### Get batch results

```
GET /api/ip-lookup/<batch_id>
```

Returns the enriched IP data for every address in the batch.

### WebSocket — real-time progress

Connect to receive live updates as each IP is resolved:

```
ws://localhost:8000/ws/batch/<batch_id>/
```

Event types pushed by the server:

| Type             | Payload                                 |
| ---------------- | --------------------------------------- |
| `batch.progress` | `{ ip, data, error, completed, total }` |
| `batch.complete` | `{ batch_id, status }`                  |

## Running Without Docker (local development)

### 1. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variables

Update `.env` so `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` point to your local Redis instance:

```env
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### 4. Run migrations

```bash
python manage.py migrate
```

### 5. Start each process in a separate terminal

```bash
# Terminal 1 — Django dev server (ASGI via Daphne)
python manage.py runserver

# Terminal 2 — Celery worker
celery -A config worker -l info
```

> Redis must be running locally on port 6379.

## Environment Variables Reference

| Variable                | Required | Description                                    |
| ----------------------- | -------- | ---------------------------------------------- |
| `SECRET_KEY`            | Yes      | Django secret key                              |
| `DEBUG`                 | No       | `True` for development, `False` for production |
| `ALLOWED_HOSTS`         | Yes      | Comma-separated list of allowed hostnames      |
| `CELERY_BROKER_URL`     | Yes      | Redis URL used as the Celery broker            |
| `CELERY_RESULT_BACKEND` | Yes      | Redis URL used to store task results           |
| `IP_INFO_API_TOKEN`     | Yes      | ipinfo.io API authentication token             |
