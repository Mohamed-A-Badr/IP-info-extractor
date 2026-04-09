from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import IPLookupBatch
from .serializers import IPLookupBatchSerializer, IPListSerializer
from .tasks import fetch_ip_info


class IPLookupBatchView(APIView):
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
