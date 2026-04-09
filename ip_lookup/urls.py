from . import views
from django.urls import path


urlpatterns = [
    path("", views.IPLookupBatchView.as_view(), name="ip-lookup-list"),
    path("<uuid:batch_id>", views.IPInfoView.as_view(), name="ip-list-info"),
]
