import uuid
from unittest.mock import MagicMock, patch

from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from httpx import HTTPStatusError
from rest_framework import status
from rest_framework.test import APITestCase

from ip_lookup.models import IPInfo, IPLookupBatch
from ip_lookup.routing import websocket_urlpatterns
from ip_lookup.serializers import (
    IPInfoSerializer,
    IPListSerializer,
    IPLookupBatchSerializer,
)
from ip_lookup.tasks import fetch_ip_info

TEST_CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}


# ===========================================================================
# Model Tests
# ===========================================================================


class IPLookupBatchModelTest(TestCase):
    def test_create_batch_with_defaults(self):
        batch = IPLookupBatch.objects.create(ips=["1.1.1.1", "8.8.8.8"], total=2)
        self.assertIsNotNone(batch.id)
        self.assertEqual(batch.status, IPLookupBatch.STATUS_PENDING)
        self.assertEqual(batch.total, 2)
        self.assertEqual(batch.completed, 0)
        self.assertIsNotNone(batch.created_at)
        self.assertIsNotNone(batch.updated_at)

    def test_str_representation(self):
        batch = IPLookupBatch.objects.create(ips=["1.1.1.1"], total=1)
        self.assertIn("Batch", str(batch))
        self.assertIn("pending", str(batch))

    def test_status_transitions_persist(self):
        batch = IPLookupBatch.objects.create(ips=["1.1.1.1"], total=1)

        batch.status = IPLookupBatch.STATUS_PROCESSING
        batch.save()
        batch.refresh_from_db()
        self.assertEqual(batch.status, IPLookupBatch.STATUS_PROCESSING)

        batch.status = IPLookupBatch.STATUS_COMPLETED
        batch.save()
        batch.refresh_from_db()
        self.assertEqual(batch.status, IPLookupBatch.STATUS_COMPLETED)

    def test_id_is_uuid(self):
        batch = IPLookupBatch.objects.create(ips=["1.1.1.1"], total=1)
        self.assertIsInstance(batch.id, uuid.UUID)

    def test_ips_stored_as_json(self):
        ips = ["1.1.1.1", "8.8.8.8", "208.67.222.222"]
        batch = IPLookupBatch.objects.create(ips=ips, total=len(ips))
        batch.refresh_from_db()
        self.assertEqual(batch.ips, ips)


class IPInfoModelTest(TestCase):
    def setUp(self):
        self.batch = IPLookupBatch.objects.create(
            ips=["8.8.8.8"],
            total=1,
            status=IPLookupBatch.STATUS_PROCESSING,
        )

    def test_create_ipinfo_with_data(self):
        info = IPInfo.objects.create(
            batch=self.batch,
            ip="8.8.8.8",
            data={"country": "US", "city": "Mountain View"},
        )
        info.refresh_from_db()
        self.assertEqual(info.ip, "8.8.8.8")
        self.assertEqual(info.data["country"], "US")
        self.assertIsNone(info.error)

    def test_create_ipinfo_with_error(self):
        info = IPInfo.objects.create(
            batch=self.batch,
            ip="8.8.8.8",
            error="HTTP 403: Forbidden",
        )
        info.refresh_from_db()
        self.assertIsNone(info.data)
        self.assertEqual(info.error, "HTTP 403: Forbidden")

    def test_str_representation(self):
        info = IPInfo.objects.create(batch=self.batch, ip="8.8.8.8")
        result = str(info)
        self.assertIn("8.8.8.8", result)
        self.assertIn(str(self.batch.id), result)

    def test_cascade_delete_removes_results(self):
        IPInfo.objects.create(batch=self.batch, ip="8.8.8.8")
        IPInfo.objects.create(batch=self.batch, ip="1.1.1.1")
        self.assertEqual(IPInfo.objects.count(), 2)
        self.batch.delete()
        self.assertEqual(IPInfo.objects.count(), 0)

    def test_related_name_access(self):
        IPInfo.objects.create(batch=self.batch, ip="8.8.8.8")
        IPInfo.objects.create(batch=self.batch, ip="1.1.1.1")
        self.assertEqual(self.batch.results.count(), 2)

    def test_supports_ipv4_and_ipv6(self):
        info_v4 = IPInfo.objects.create(batch=self.batch, ip="8.8.8.8")
        info_v6 = IPInfo.objects.create(
            batch=self.batch, ip="2001:4860:4860::8888"
        )
        self.assertEqual(info_v4.ip, "8.8.8.8")
        self.assertEqual(info_v6.ip, "2001:4860:4860::8888")


# ===========================================================================
# Serializer Tests
# ===========================================================================


class IPListSerializerTest(TestCase):
    def _validate(self, ips):
        s = IPListSerializer(data={"ips": ips})
        s.is_valid()
        return s

    def test_valid_single_ipv4(self):
        s = self._validate(["8.8.8.8"])
        self.assertTrue(s.is_valid())
        self.assertEqual(s.validated_data["ips"], ["8.8.8.8"])

    def test_valid_multiple_ips(self):
        s = self._validate(["8.8.8.8", "1.1.1.1", "208.67.222.222"])
        self.assertTrue(s.is_valid())
        self.assertEqual(len(s.validated_data["ips"]), 3)

    def test_valid_ipv6(self):
        s = self._validate(["2001:4860:4860::8888"])
        self.assertTrue(s.is_valid())

    def test_invalid_ip_rejected(self):
        s = self._validate(["not-an-ip"])
        self.assertFalse(s.is_valid())

    def test_hostname_rejected(self):
        s = self._validate(["google.com"])
        self.assertFalse(s.is_valid())

    def test_duplicates_are_removed(self):
        s = self._validate(["8.8.8.8", "8.8.8.8", "1.1.1.1"])
        self.assertTrue(s.is_valid())
        self.assertEqual(s.validated_data["ips"], ["8.8.8.8", "1.1.1.1"])

    def test_whitespace_stripped(self):
        s = self._validate(["  8.8.8.8  "])
        self.assertTrue(s.is_valid())
        self.assertEqual(s.validated_data["ips"], ["8.8.8.8"])

    def test_empty_list_invalid(self):
        s = self._validate([])
        self.assertFalse(s.is_valid())

    def test_exceeds_100_limit_invalid(self):
        s = self._validate([f"1.1.1.{i}" for i in range(101)])
        self.assertFalse(s.is_valid())

    def test_exactly_100_ips_valid(self):
        ips = []
        for a in range(1, 11):
            for b in range(1, 11):
                ips.append(f"10.{a}.{b}.1")
        s = self._validate(ips[:100])
        self.assertTrue(s.is_valid())
        self.assertEqual(len(s.validated_data["ips"]), 100)

    def test_mixed_valid_and_invalid_rejected(self):
        s = self._validate(["8.8.8.8", "bad-ip"])
        self.assertFalse(s.is_valid())


class IPLookupBatchSerializerTest(TestCase):
    def test_serializes_all_expected_fields(self):
        batch = IPLookupBatch.objects.create(ips=["8.8.8.8"], total=1)
        data = IPLookupBatchSerializer(batch).data
        for field in ("id", "status", "total", "completed", "ips", "created_at"):
            self.assertIn(field, data)

    def test_correct_field_values(self):
        batch = IPLookupBatch.objects.create(
            ips=["8.8.8.8", "1.1.1.1"],
            total=2,
            status=IPLookupBatch.STATUS_PROCESSING,
        )
        data = IPLookupBatchSerializer(batch).data
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["completed"], 0)
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["ips"], ["8.8.8.8", "1.1.1.1"])


class IPInfoSerializerTest(TestCase):
    def setUp(self):
        self.batch = IPLookupBatch.objects.create(ips=["8.8.8.8"], total=1)

    def test_serializes_successful_result(self):
        info = IPInfo.objects.create(
            batch=self.batch,
            ip="8.8.8.8",
            data={"country": "US"},
        )
        data = IPInfoSerializer(info).data
        self.assertEqual(data["ip"], "8.8.8.8")
        self.assertEqual(data["data"]["country"], "US")
        self.assertIsNone(data["error"])
        self.assertIn("created_at", data)

    def test_serializes_failed_result(self):
        info = IPInfo.objects.create(
            batch=self.batch,
            ip="8.8.8.8",
            error="HTTP 403: Forbidden",
        )
        data = IPInfoSerializer(info).data
        self.assertIsNone(data["data"])
        self.assertEqual(data["error"], "HTTP 403: Forbidden")


# ===========================================================================
# API View Tests
# ===========================================================================


class IPLookupBatchViewTest(APITestCase):
    def _post(self, ips):
        return self.client.post("/api/ip-lookup/", {"ips": ips}, format="json")

    @patch("ip_lookup.views.fetch_ip_info")
    def test_post_returns_200(self, mock_task):
        mock_task.delay.return_value = None
        response = self._post(["8.8.8.8"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("ip_lookup.views.fetch_ip_info")
    def test_post_creates_batch_in_db(self, mock_task):
        mock_task.delay.return_value = None
        self._post(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(IPLookupBatch.objects.count(), 1)
        batch = IPLookupBatch.objects.first()
        self.assertEqual(batch.total, 2)
        self.assertEqual(batch.status, IPLookupBatch.STATUS_PROCESSING)

    @patch("ip_lookup.views.fetch_ip_info")
    def test_post_dispatches_one_task_per_ip(self, mock_task):
        mock_task.delay.return_value = None
        self._post(["8.8.8.8", "1.1.1.1", "208.67.222.222"])
        self.assertEqual(mock_task.delay.call_count, 3)

    @patch("ip_lookup.views.fetch_ip_info")
    def test_post_response_contains_batch_fields(self, mock_task):
        mock_task.delay.return_value = None
        response = self._post(["8.8.8.8"])
        for field in ("id", "status", "total", "completed"):
            self.assertIn(field, response.data)

    @patch("ip_lookup.views.fetch_ip_info")
    def test_post_deduplicates_ips_before_dispatching(self, mock_task):
        mock_task.delay.return_value = None
        response = self._post(["8.8.8.8", "8.8.8.8"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        batch = IPLookupBatch.objects.first()
        self.assertEqual(batch.total, 1)
        self.assertEqual(mock_task.delay.call_count, 1)

    def test_post_invalid_ip_returns_400(self):
        response = self._post(["not-an-ip"])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_empty_list_returns_400(self):
        response = self._post([])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_missing_ips_key_returns_400(self):
        response = self.client.post("/api/ip-lookup/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class IPInfoViewTest(APITestCase):
    def setUp(self):
        self.batch = IPLookupBatch.objects.create(
            ips=["8.8.8.8", "1.1.1.1"],
            total=2,
            status=IPLookupBatch.STATUS_COMPLETED,
            completed=2,
        )
        IPInfo.objects.create(
            batch=self.batch,
            ip="8.8.8.8",
            data={"country": "US"},
        )
        IPInfo.objects.create(
            batch=self.batch,
            ip="1.1.1.1",
            data={"country": "AU"},
        )

    def test_get_returns_200_with_results(self):
        response = self.client.get(f"/api/ip-lookup/{self.batch.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_get_returns_correct_ip_data(self):
        response = self.client.get(f"/api/ip-lookup/{self.batch.id}")
        ips = {item["ip"] for item in response.data}
        self.assertIn("8.8.8.8", ips)
        self.assertIn("1.1.1.1", ips)

    def test_get_nonexistent_batch_returns_404(self):
        response = self.client.get(f"/api/ip-lookup/{uuid.uuid4()}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_batch_with_no_results_returns_404(self):
        empty_batch = IPLookupBatch.objects.create(
            ips=["9.9.9.9"], total=1, status=IPLookupBatch.STATUS_PROCESSING
        )
        response = self.client.get(f"/api/ip-lookup/{empty_batch.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# Celery Task Tests
# ===========================================================================


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
)
class FetchIPInfoTaskTest(TestCase):
    def setUp(self):
        self.batch = IPLookupBatch.objects.create(
            ips=["8.8.8.8"],
            total=1,
            status=IPLookupBatch.STATUS_PROCESSING,
        )

    def _mock_success(self, mock_client_cls, data):
        mock_resp = MagicMock()
        mock_resp.json.return_value = data
        mock_resp.raise_for_status.return_value = None
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    def _mock_http_error(self, mock_client_cls, status_code):
        mock_resp = MagicMock()
        mock_error_resp = MagicMock()
        mock_error_resp.status_code = status_code
        mock_error_resp.text = f"Error {status_code}"
        mock_resp.raise_for_status.side_effect = HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_error_resp,
        )
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    @patch("ip_lookup.tasks.httpx.Client")
    def test_successful_lookup_creates_ipinfo_record(self, mock_client_cls):
        ip_data = {"ip": "8.8.8.8", "country": "US", "city": "Mountain View"}
        self._mock_success(mock_client_cls, ip_data)

        fetch_ip_info(str(self.batch.id), "8.8.8.8")

        info = IPInfo.objects.get(batch=self.batch, ip="8.8.8.8")
        self.assertEqual(info.data, ip_data)
        self.assertIsNone(info.error)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_successful_lookup_increments_completed_counter(self, mock_client_cls):
        self._mock_success(mock_client_cls, {"ip": "8.8.8.8"})

        fetch_ip_info(str(self.batch.id), "8.8.8.8")

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.completed, 1)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_last_ip_marks_batch_completed(self, mock_client_cls):
        self._mock_success(mock_client_cls, {"ip": "8.8.8.8"})

        fetch_ip_info(str(self.batch.id), "8.8.8.8")

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, IPLookupBatch.STATUS_COMPLETED)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_http_error_stores_error_text(self, mock_client_cls):
        self._mock_http_error(mock_client_cls, 403)

        fetch_ip_info(str(self.batch.id), "8.8.8.8")

        info = IPInfo.objects.get(batch=self.batch, ip="8.8.8.8")
        self.assertIsNone(info.data)
        self.assertIn("403", info.error)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_network_error_stores_error_text(self, mock_client_cls):
        mock_client_cls.return_value.__enter__.return_value.get.side_effect = (
            Exception("Connection refused")
        )

        fetch_ip_info(str(self.batch.id), "8.8.8.8")

        info = IPInfo.objects.get(batch=self.batch, ip="8.8.8.8")
        self.assertIsNone(info.data)
        self.assertIn("Connection refused", info.error)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_error_still_increments_completed_counter(self, mock_client_cls):
        self._mock_http_error(mock_client_cls, 429)

        fetch_ip_info(str(self.batch.id), "8.8.8.8")

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.completed, 1)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_batch_stays_processing_until_all_ips_done(self, mock_client_cls):
        batch = IPLookupBatch.objects.create(
            ips=["8.8.8.8", "1.1.1.1"],
            total=2,
            status=IPLookupBatch.STATUS_PROCESSING,
        )
        self._mock_success(mock_client_cls, {"ip": "8.8.8.8"})

        fetch_ip_info(str(batch.id), "8.8.8.8")

        batch.refresh_from_db()
        self.assertEqual(batch.status, IPLookupBatch.STATUS_PROCESSING)
        self.assertEqual(batch.completed, 1)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_batch_completed_after_all_ips_done(self, mock_client_cls):
        batch = IPLookupBatch.objects.create(
            ips=["8.8.8.8", "1.1.1.1"],
            total=2,
            status=IPLookupBatch.STATUS_PROCESSING,
        )
        self._mock_success(mock_client_cls, {"ip": "any"})

        fetch_ip_info(str(batch.id), "8.8.8.8")
        fetch_ip_info(str(batch.id), "1.1.1.1")

        batch.refresh_from_db()
        self.assertEqual(batch.status, IPLookupBatch.STATUS_COMPLETED)
        self.assertEqual(batch.completed, 2)

    @patch("ip_lookup.tasks.httpx.Client")
    def test_ipinfo_record_created_for_each_ip(self, mock_client_cls):
        batch = IPLookupBatch.objects.create(
            ips=["8.8.8.8", "1.1.1.1", "208.67.222.222"],
            total=3,
            status=IPLookupBatch.STATUS_PROCESSING,
        )
        self._mock_success(mock_client_cls, {"ip": "any"})

        for ip in batch.ips:
            fetch_ip_info(str(batch.id), ip)

        self.assertEqual(IPInfo.objects.filter(batch=batch).count(), 3)


# ===========================================================================
# WebSocket Consumer Tests
# ===========================================================================


@override_settings(CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
class BatchStatusConsumerTest(TransactionTestCase):
    def _make_communicator(self, batch_id):
        return WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/batch/{batch_id}/",
        )

    async def test_connect_accepted(self):
        comm = self._make_communicator(str(uuid.uuid4()))
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        await comm.disconnect()

    async def test_disconnect_does_not_raise(self):
        comm = self._make_communicator(str(uuid.uuid4()))
        await comm.connect()
        await comm.disconnect()

    async def test_receives_batch_progress_event(self):
        batch_id = str(uuid.uuid4())
        comm = self._make_communicator(batch_id)
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        await get_channel_layer().group_send(
            f"batch_{batch_id}",
            {
                "type": "batch.progress",
                "ip": "8.8.8.8",
                "data": {"country": "US"},
                "error": None,
                "completed": 1,
                "total": 5,
            },
        )

        response = await comm.receive_json_from()
        self.assertEqual(response["type"], "batch.progress")
        self.assertEqual(response["ip"], "8.8.8.8")
        self.assertEqual(response["completed"], 1)
        self.assertEqual(response["total"], 5)
        self.assertIsNone(response["error"])

        await comm.disconnect()

    async def test_receives_batch_complete_event(self):
        batch_id = str(uuid.uuid4())
        comm = self._make_communicator(batch_id)
        await comm.connect()

        await get_channel_layer().group_send(
            f"batch_{batch_id}",
            {
                "type": "batch.complete",
                "batch_id": batch_id,
                "status": "completed",
            },
        )

        response = await comm.receive_json_from()
        self.assertEqual(response["type"], "batch.complete")
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["batch_id"], batch_id)

        await comm.disconnect()

    async def test_multiple_clients_same_batch_both_receive(self):
        batch_id = str(uuid.uuid4())
        comm1 = self._make_communicator(batch_id)
        comm2 = self._make_communicator(batch_id)

        await comm1.connect()
        await comm2.connect()

        await get_channel_layer().group_send(
            f"batch_{batch_id}",
            {
                "type": "batch.progress",
                "ip": "8.8.8.8",
                "data": None,
                "error": None,
                "completed": 1,
                "total": 1,
            },
        )

        response1 = await comm1.receive_json_from()
        response2 = await comm2.receive_json_from()
        self.assertEqual(response1["ip"], "8.8.8.8")
        self.assertEqual(response2["ip"], "8.8.8.8")

        await comm1.disconnect()
        await comm2.disconnect()

    async def test_different_batch_groups_are_isolated(self):
        batch_id_1 = str(uuid.uuid4())
        batch_id_2 = str(uuid.uuid4())

        comm1 = self._make_communicator(batch_id_1)
        comm2 = self._make_communicator(batch_id_2)

        await comm1.connect()
        await comm2.connect()

        await get_channel_layer().group_send(
            f"batch_{batch_id_1}",
            {
                "type": "batch.progress",
                "ip": "8.8.8.8",
                "data": None,
                "error": None,
                "completed": 1,
                "total": 1,
            },
        )

        response1 = await comm1.receive_json_from()
        self.assertEqual(response1["ip"], "8.8.8.8")

        # comm2 is on a different group and should receive nothing
        self.assertTrue(await comm2.receive_nothing())

        await comm1.disconnect()
        await comm2.disconnect()
