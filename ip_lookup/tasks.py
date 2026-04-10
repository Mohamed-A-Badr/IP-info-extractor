import logging
import os

import httpx
from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.db.models import F

from .models import IPInfo, IPLookupBatch

logger = logging.getLogger(__name__)

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
        logger.warning("IP lookup failed for %s (batch %s): %s", ip, batch_id, error)
    except Exception as exc:
        data = None
        error = str(exc)
        logger.exception("Unexpected error fetching IP %s (batch %s)", ip, batch_id)

    IPInfo.objects.create(batch_id=batch_id, ip=ip, error=error, data=data)

    IPLookupBatch.objects.filter(id=batch_id).update(completed=F("completed") + 1)
    batch = IPLookupBatch.objects.only("completed", "total").get(id=batch_id)

    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.error(
            "No channel layer configured — WebSocket notifications are disabled."
        )
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

    just_completed = IPLookupBatch.objects.filter(
        id=batch_id,
        completed=F("total"),
        status=IPLookupBatch.STATUS_PROCESSING,
    ).update(status=IPLookupBatch.STATUS_COMPLETED)

    if just_completed:
        logger.info("Batch %s completed.", batch_id)
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "batch.complete",
                "batch_id": batch_id,
                "status": IPLookupBatch.STATUS_COMPLETED,
            },
        )
