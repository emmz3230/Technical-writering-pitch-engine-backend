from django.urls import path
from .views import (
    LeadListView,
    GenerateBatchView,
    RolloverQueueView,
    WorkerStatusView,
    TogglePauseView,
    ToggleAutoDailyView,
    ProcessNowView,
    SendSingleLeadView,
    ResetQueueView
)

urlpatterns = [
    path('leads/', LeadListView.as_view(), name='lead-list'),
    path('queue/generate/', GenerateBatchView.as_view(), name='queue-generate'),
    path('queue/rollover/', RolloverQueueView.as_view(), name='queue-rollover'),
    path('worker/status/', WorkerStatusView.as_view(), name='worker-status'),
    path('worker/toggle-pause/', TogglePauseView.as_view(), name='worker-toggle-pause'),
    path('worker/toggle-auto-daily/', ToggleAutoDailyView.as_view(), name='worker-toggle-auto-daily'),
    path('queue/process-now/', ProcessNowView.as_view(), name='queue-process-now'),
    path('leads/<int:pk>/send-now/', SendSingleLeadView.as_view(), name='lead-send-now'),
    path('queue/reset/', ResetQueueView.as_view(), name='queue-reset'),
]
