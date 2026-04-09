import ipaddress
from rest_framework import serializers
from .models import IPLookupBatch


class IPListSerializer(serializers.Serializer):
    ips = serializers.ListField(child=serializers.CharField(), min_length=1)

    def validate_ips(self, value):
        validated = []
        errors = []
        for raw in value:
            ip_str = raw.strip()
            try:
                ipaddress.ip_address(ip_str)
                validated.append(ip_str)
            except ValueError:
                errors.append(f"'{ip_str}' is not a valid IP address.")
        if errors:
            raise serializers.ValidationError(errors)
        return validated


class IPLookupBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = IPLookupBatch
        fields = ["id", "status", "total", "completed", "ips", "created_at"]
