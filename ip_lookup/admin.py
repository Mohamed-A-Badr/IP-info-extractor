from django.contrib import admin
from .models import IPLookupBatch


@admin.register(IPLookupBatch)
class IPLookupBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "total", "completed", "created_at"]
    readonly_fields = ["id", "created_at"]
