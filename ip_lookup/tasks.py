import os

import httpx
from celery import shared_task
from django.db.models import F

from .models import IPInfo, IPLookupBatch

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

    IPInfo.objects.create(batch_id=batch_id, ip=ip, error=error, data=data)

    IPLookupBatch.objects.filter(id=batch_id).update(completed=F("completed") + 1)
    batch = IPLookupBatch.objects.get(id=batch_id)

    if batch.completed >= batch.total:
        IPLookupBatch.objects.filter(id=batch_id).update(
            status=IPLookupBatch.STATUS_COMPLETED
        )

    print(data)
    print(batch)
