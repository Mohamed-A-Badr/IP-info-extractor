import ipaddress
from rest_framework import serializers
from .models import IPLookupBatch, IPInfo

MAX_IPS_PER_BATCH = 100


class IPListSerializer(serializers.Serializer):
    ips = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=MAX_IPS_PER_BATCH,
    )

    def validate_ips(self, value):
        validated = []
        errors = []
        seen = set()

        for raw in value:
            ip_str = raw.strip()
            try:
                ipaddress.ip_address(ip_str)
            except ValueError:
                errors.append(f"'{ip_str}' is not a valid IP address.")
                continue

            if ip_str in seen:
                continue
            seen.add(ip_str)
            validated.append(ip_str)

        if errors:
            raise serializers.ValidationError(errors)
        return validated


class IPLookupBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = IPLookupBatch
        fields = ["id", "status", "total", "completed", "ips", "created_at"]


class IPInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = IPInfo
        fields = ["ip", "data", "error", "created_at"]
