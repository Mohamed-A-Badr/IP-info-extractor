from django.urls import re_path

from . import consumers

_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

websocket_urlpatterns = [
    re_path(
        rf"ws/batch/(?P<batch_id>{_UUID_RE})/$",
        consumers.BatchStatusConsumer.as_asgi(),
    ),
]
