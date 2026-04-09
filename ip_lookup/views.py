from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_list_or_404, render

from .models import IPLookupBatch, IPInfo
from .serializers import IPLookupBatchSerializer, IPListSerializer, IPInfoSerializer
from .tasks import fetch_ip_info


# ── DRF API views ─────────────────────────────────────────────────────────────

class IPLookupBatchView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=IPListSerializer,
        responses={200: IPLookupBatchSerializer},
    )
    def post(self, request):
        serializer = IPListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ips = serializer.validated_data["ips"]

        batch = IPLookupBatch.objects.create(
            ips=ips,
            total=len(ips),
            status=IPLookupBatch.STATUS_PROCESSING,
        )

        for ip in ips:
            fetch_ip_info.delay(str(batch.id), ip)

        return Response(
            IPLookupBatchSerializer(batch).data,
            status=status.HTTP_200_OK,
        )


class IPInfoView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: IPInfoSerializer(many=True)},
    )
    def get(self, request, batch_id):
        ip_list = get_list_or_404(IPInfo, batch_id=batch_id)
        serializer = IPInfoSerializer(ip_list, many=True)
        return Response(serializer.data)


# ── Template views (UI) ────────────────────────────────────────────────────────

async def home_view(request):
    batches = [b async for b in IPLookupBatch.objects.order_by("-created_at")]
    return render(request, "ip_lookup/home.html", {"batches": batches})


async def submit_view(request):
    return render(request, "ip_lookup/submit.html")


async def batch_detail_view(request, batch_id):
    return render(request, "ip_lookup/batch_detail.html", {"batch_id": str(batch_id)})
