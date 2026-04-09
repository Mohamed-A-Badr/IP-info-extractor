from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/batch/(?P<batch_id>[^/]+)/$", consumers.BatchStatusConsumer.as_asgi()),
]
