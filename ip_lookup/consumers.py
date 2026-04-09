import json

from channels.generic.websocket import AsyncWebsocketConsumer


class BatchStatusConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer that streams real-time progress updates for an IP lookup batch.

    Connect:  ws://<host>/ws/batch/<batch_id>/
    Receives: { "type": "batch.progress", "ip": "...", "data": {...}, "completed": N, "total": N }
              { "type": "batch.complete", "batch_id": "..." }
    """

    async def connect(self):
        self.batch_id = self.scope["url_route"]["kwargs"]["batch_id"]
        self.group_name = f"batch_{self.batch_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def batch_progress(self, event):
        await self.send(text_data=json.dumps(event))

    async def batch_complete(self, event):
        await self.send(text_data=json.dumps(event))
