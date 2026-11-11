from rest_framework import views, status, response
from django.utils import timezone
from .models import Lead, WorkerState
from .serializers import LeadSerializer, WorkerStateSerializer
from .audit_engine import prepare_daily_batch, generate_lead_batch
from .scheduler import process_due_pitches, send_lead_email, start_background_scheduler


class LeadListView(views.APIView):
    """
    Returns all leads in the cold pitch engine, ordered by scheduled_send_time.
    Supports filtering by ?status=queued|sent|failed.
    """
    def get(self, request):
        status_filter = request.query_params.get('status')
        queryset = Lead.objects.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        serializer = LeadSerializer(queryset, many=True)
        return response.Response({
            'success': True,
            'leads': serializer.data
        })


class GenerateBatchView(views.APIView):
    """
    Generates a batch of up to 30 leads across global English-speaking markets (US, UK, CA, AU, IE, NZ).
    Automatically rolls over previous unsent/failed leads and generates fresh unique leads from the
    infinite catalog for remaining slots, spacing out their scheduled_send_time by exactly 20-minute increments.
    """
    def post(self, request):
        count = int(request.data.get('count', 30))
        include_rollover = request.data.get('include_rollover', True)
        count = min(count, 30)

        # Ensure background scheduler is running
        start_background_scheduler()

        leads = prepare_daily_batch(count=count, include_rollover=include_rollover)
        serializer = LeadSerializer(leads, many=True)

        rollover_count = sum(1 for l in leads if getattr(l, 'is_rollover', False))
        new_count = len(leads) - rollover_count

        return response.Response({
            'success': True,
            'message': f"Scheduled {len(leads)} leads: {rollover_count} rolled-over unsent, {new_count} brand-new fresh leads.",
            'batch_size': len(leads),
            'rollover_count': rollover_count,
            'new_count': new_count,
            'leads': serializer.data
        }, status=status.HTTP_201_CREATED)


class RolloverQueueView(views.APIView):
    """
    Explicitly reschedules all unsent and failed leads from past days/runs
    into the active queue, spaced out starting from now by 20 minutes increments.
    """
    def post(self, request):
        count = int(request.data.get('count', 30))
        leads = prepare_daily_batch(count=count, include_rollover=True)
        serializer = LeadSerializer(leads, many=True)

        return response.Response({
            'success': True,
            'message': f"Rollover complete: {len(leads)} leads scheduled in 20-minute increments.",
            'leads': serializer.data
        })


class WorkerStatusView(views.APIView):
    """
    Returns the real-time background queue worker state:
    pause status, daily pitch count (out of 30), unsent leads count, and next scheduled dispatch.
    """
    def get(self, request):
        state = WorkerState.get_state()
        serializer = WorkerStateSerializer(state)
        return response.Response({
            'success': True,
            'worker': serializer.data,
            'server_time': timezone.now()
        })


class TogglePauseView(views.APIView):
    """
    Instantly pauses or resumes the backend background worker loop.
    """
    def post(self, request):
        state = WorkerState.get_state()
        explicit_state = request.data.get('is_paused')

        if explicit_state is not None:
            state.is_paused = bool(explicit_state)
        else:
            state.is_paused = not state.is_paused

        state.last_run_status = "Queue PAUSED by user." if state.is_paused else "Queue RESUMED by user."
        state.save()

        return response.Response({
            'success': True,
            'is_paused': state.is_paused,
            'message': f"Background queue is now {'PAUSED' if state.is_paused else 'ACTIVE'}."
        })


class ToggleAutoDailyView(views.APIView):
    """
    Toggles whether the background scheduler automatically generates fresh daily 30-lead batches.
    """
    def post(self, request):
        state = WorkerState.get_state()
        state.auto_generate_daily = not state.auto_generate_daily
        state.save(update_fields=['auto_generate_daily'])

        return response.Response({
            'success': True,
            'auto_generate_daily': state.auto_generate_daily,
            'message': f"Auto Daily Generation is now {'ENABLED' if state.auto_generate_daily else 'DISABLED'}."
        })


class ProcessNowView(views.APIView):
    """
    Triggers an immediate evaluation cycle of the background scheduler.
    """
    def post(self, request):
        start_background_scheduler()
        dispatched = process_due_pitches()
        state = WorkerState.get_state()
        serializer = WorkerStateSerializer(state)

        return response.Response({
            'success': True,
            'dispatched_count': dispatched,
            'worker': serializer.data
        })


class SendSingleLeadView(views.APIView):
    """
    Triggers an immediate silent SMTP dispatch for a specific lead.
    """
    def post(self, request, pk):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist:
            return response.Response({'error': 'Lead not found'}, status=status.HTTP_404_NOT_FOUND)

        success = send_lead_email(lead)
        serializer = LeadSerializer(lead)
        return response.Response({
            'success': success,
            'lead': serializer.data
        })


class ResetQueueView(views.APIView):
    """
    Clears all leads from database for testing / fresh batch generations.
    """
    def post(self, request):
        Lead.objects.all().delete()
        state = WorkerState.get_state()
        state.daily_sent_count = 0
        state.last_run_status = "Idle - Queue reset"
        state.save()

        return response.Response({
            'success': True,
            'message': 'Queue and daily count reset successfully.'
        })
