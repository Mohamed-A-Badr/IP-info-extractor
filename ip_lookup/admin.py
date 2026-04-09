from django.contrib import admin
from .models import IPLookupBatch, IPInfo


class IPInfoInline(admin.TabularInline):
    model = IPInfo
    extra = 0
    readonly_fields = ["ip", "data", "error", "created_at"]
    can_delete = False
    show_change_link = True


@admin.register(IPLookupBatch)
class IPLookupBatchAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "total", "completed", "created_at"]
    readonly_fields = ["id", "created_at"]
    inlines = [IPInfoInline]


@admin.register(IPInfo)
class IPInfoAdmin(admin.ModelAdmin):
    list_display = ["id", "ip", "batch", "created_at"]
    readonly_fields = ["created_at"]
