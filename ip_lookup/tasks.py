import os

import httpx
from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
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

    # Atomically increment; read back the new value for the progress message
    IPLookupBatch.objects.filter(id=batch_id).update(completed=F("completed") + 1)
    batch = IPLookupBatch.objects.get(id=batch_id)

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    group_name = f"batch_{batch_id}"

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "batch.progress",
            "ip": ip,
            "data": data,
            "error": error,
            "completed": batch.completed,
            "total": batch.total,
        },
    )

    # Atomic completion check — only the task whose increment hit the total wins.
    # The filter matches only while status is still 'processing' AND completed == total,
    # so even if two tasks race here, exactly one UPDATE succeeds (returns 1).
    just_completed = IPLookupBatch.objects.filter(
        id=batch_id,
        completed=F("total"),
        status=IPLookupBatch.STATUS_PROCESSING,
    ).update(status=IPLookupBatch.STATUS_COMPLETED)

    if just_completed:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "batch.complete",
                "batch_id": batch_id,
                "status": IPLookupBatch.STATUS_COMPLETED,
            },
        )
