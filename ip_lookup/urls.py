from . import views
from django.urls import path


urlpatterns = [
    path("", views.IPLookupBatchView.as_view(), name="ip-lookup-list"),
]
