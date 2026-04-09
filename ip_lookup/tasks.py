import os

import httpx
from celery import shared_task

API_TOKEN = os.getenv("IP_INFO_API_TOKEN", "")


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def fetch_ip_info(self, batch_id: str, ip: str):
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get(
                f"https://api.ipinfo.io/lite/{ip}",
                headers={"Authorization": f"Bearer {API_TOKEN}"},
            )
            response.raise_for_status()
            data = response.json()
        error = None
    except httpx.HTTPStatusError as exc:
        data = None
        error = f"HTTP {exc.response.status_code}: {exc.response.text}"
    except Exception as exc:
        data = None
        error = str(exc)

    print(data)
