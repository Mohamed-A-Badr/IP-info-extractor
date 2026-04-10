import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class BatchStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.batch_id = self.scope["url_route"]["kwargs"]["batch_id"]
        self.group_name = f"batch_{self.batch_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.debug("WebSocket connected: %s", self.group_name)

    async def disconnect(self, close_code):
        if not hasattr(self, "group_name"):
            return
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.debug(
            "WebSocket disconnected: %s (code=%s)", self.group_name, close_code
        )

    async def batch_progress(self, event):
        await self.send(text_data=json.dumps(event))

    async def batch_complete(self, event):
        await self.send(text_data=json.dumps(event))
