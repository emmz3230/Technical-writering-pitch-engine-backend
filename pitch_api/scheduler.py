"""
Continuous Background Scheduler & Silent SMTP Email Dispatcher.
Checks the database every minute for leads whose scheduled_send_time <= current_time,
validates pause state and daily 30-pitch caps, dispatches via Django SMTP backend,
and discovers verified prospects for the daily queue.
"""

import time
import logging
import threading
from datetime import timedelta, date
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.validators import validate_email
from django.core.mail import EmailMessage
from django.conf import settings
from .models import Lead, WorkerState
from .audit_engine import prepare_daily_batch

logger = logging.getLogger('pitch_scheduler')
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] [Scheduler] %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Global thread control
_scheduler_thread = None
_stop_event = threading.Event()
_scheduler_lock = threading.Lock()


def send_lead_email(lead):
    """
    Sends cold pitch email silently via Django's configured SMTP backend.
    Updates lead status to 'sent' (with timestamp) or 'failed' (with error message).
    """
    recipient = (lead.contact_email or '').strip()
    if not recipient or recipient.lower().startswith('leads-demo+'):
        lead.status = 'failed'
        lead.error_message = (
            "No real contact email is available. Add a valid recipient address before sending."
        )
        lead.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.warning(f"Not sending to {lead.company_name}: no real contact email is available.")
        return False

    try:
        validate_email(recipient)
    except ValidationError:
        lead.status = 'failed'
        lead.error_message = "The contact email address is invalid. Correct it before sending."
        lead.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.warning(f"Not sending to {lead.company_name}: invalid contact email address.")
        return False

    logger.info(f"Dispatching cold pitch to {lead.company_name} <{recipient}>...")

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', 'noreply@coldpitchengine.local')
    recipient_list = [recipient]

    try:
        email = EmailMessage(
            subject=lead.subject,
            body=lead.body,
            from_email=from_email,
            to=recipient_list,
        )

        sent_count = email.send(fail_silently=False)

        if sent_count > 0:
            lead.status = 'sent'
            lead.sent_at = timezone.now()
            lead.error_message = None
            lead.save(update_fields=['status', 'sent_at', 'error_message', 'updated_at'])

            state = WorkerState.get_state()
            state.increment_daily_count()

            logger.info(f"SUCCESS: Email sent to {lead.contact_email} for {lead.company_name} at {lead.sent_at}")
            return True
        else:
            lead.status = 'failed'
            lead.error_message = "SMTP backend reported 0 emails dispatched."
            lead.save(update_fields=['status', 'error_message', 'updated_at'])
            logger.warning(f"FAILED: 0 emails delivered for {lead.contact_email}")
            return False

    except Exception as exc:
        lead.status = 'failed'
        lead.error_message = str(exc)
        lead.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.error(f"FAILED: Error sending pitch to {lead.contact_email}: {exc}")
        return False


def check_and_auto_generate_daily_batch(state):
    """
    Automated Daily Schedule & Rollover Check:
    1. If the day has rolled over, resets daily_sent_count.
    2. If automatic generation is enabled and the queue is empty, make at most one
       verified-prospect discovery attempt per day.
    """
    today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
    reset_date = state.last_reset_date
    if hasattr(reset_date, 'date'):
        reset_date = reset_date.date()

    daily_limit = getattr(settings, 'DAILY_PITCH_LIMIT', 30)
    day_rolled_over = reset_date < today

    if day_rolled_over:
        logger.info(f"[Daily Auto-Scheduler] New day detected ({today}). Resetting daily sent counter from {state.daily_sent_count} to 0.")
        state.daily_sent_count = 0
        state.last_reset_date = today
        state.save(update_fields=['daily_sent_count', 'last_reset_date', 'updated_at'])

    if state.auto_generate_daily and not state.is_paused:
        active_queued_count = Lead.objects.filter(status='queued').count()
        # If queue is depleted and we haven't reached daily cap
        if (
            active_queued_count == 0
            and state.daily_sent_count < daily_limit
            and state.last_auto_generate_date != today
        ):
            needed = daily_limit - state.daily_sent_count
            state.last_auto_generate_date = today
            state.save(update_fields=['last_auto_generate_date', 'updated_at'])
            logger.info(f"[Daily Auto-Scheduler] Active queue empty. Discovering up to {needed} verified leads...")
            batch = prepare_daily_batch(count=needed, include_rollover=True)
            logger.info(f"[Daily Auto-Scheduler] Scheduled {len(batch)} verified leads.")
            state.last_run_status = (
                f"Auto-scheduled {len(batch)} verified leads"
                if batch else "No verified prospects found today; try generating again later."
            )
            state.save(update_fields=['last_run_status'])


def process_due_pitches():
    """
    Single evaluation iteration of the background queue:
    1. Runs the automated daily rollover & queue replenishment check.
    2. Check if the worker is paused by the user.
    3. Enforce the strict 30 pitches/day domain safety cap.
    4. Query leads with status='queued' and scheduled_send_time <= current_time.
    5. Silently send via SMTP and record outcomes.
    """
    state = WorkerState.get_state()
    state.last_poll_time = timezone.now()

    # 1. Automated daily queue generation & rollover check
    try:
        check_and_auto_generate_daily_batch(state)
    except Exception as exc:
        logger.error(f"Error checking daily auto-generation: {exc}")

    # 2. Check Pause status
    if state.is_paused:
        state.last_run_status = 'Queue is PAUSED by user.'
        state.save(update_fields=['last_poll_time', 'last_run_status'])
        logger.info("Background queue is paused. Skipping scheduled dispatches.")
        return 0

    # 3. Check Daily Cap (Strict 30 pitches per day)
    daily_limit = getattr(settings, 'DAILY_PITCH_LIMIT', 30)
    if not state.can_send_today(max_limit=daily_limit):
        state.last_run_status = f"Daily limit of {daily_limit} pitches reached. Pausing until tomorrow."
        state.save(update_fields=['last_poll_time', 'last_run_status'])
        logger.warning(f"Daily cap of {daily_limit} pitches reached ({state.daily_sent_count}/{daily_limit}). Postponing.")
        return 0

    # 4. Query due leads
    now = timezone.now()
    due_leads = Lead.objects.filter(
        status='queued',
        scheduled_send_time__lte=now
    ).order_by('scheduled_send_time')

    due_count = due_leads.count()
    if due_count == 0:
        next_lead = Lead.objects.filter(status='queued').order_by('scheduled_send_time').first()
        if next_lead:
            delta = next_lead.scheduled_send_time - now
            mins = int(delta.total_seconds() // 60)
            secs = int(delta.total_seconds() % 60)
            rollover_tag = " (Rollover)" if next_lead.is_rollover else ""
            state.last_run_status = f"Idle - Next pitch in {mins}m {secs}s ({next_lead.company_name}{rollover_tag})"
        else:
            state.last_run_status = "Idle - Queue is empty"
        state.save(update_fields=['last_poll_time', 'last_run_status'])
        return 0

    state.last_run_status = f"Dispatching {due_count} due pitch(es)..."
    state.save(update_fields=['last_poll_time', 'last_run_status'])

    # 5. Dispatch due leads respecting remaining daily quota
    remaining_quota = daily_limit - state.daily_sent_count
    dispatched_count = 0

    for lead in due_leads[:remaining_quota]:
        state.refresh_from_db()
        if state.is_paused:
            logger.info("Worker paused mid-batch.")
            break

        send_lead_email(lead)
        dispatched_count += 1

    return dispatched_count


def continuous_worker_loop(poll_interval=60):
    """
    Continuous worker loop that checks the queue every poll_interval seconds (default: 60s).
    """
    logger.info(f"Cold Pitch Background Scheduler active. Polling database every {poll_interval}s...")
    while not _stop_event.is_set():
        try:
            process_due_pitches()
        except Exception as exc:
            logger.exception(f"Unexpected error in background worker loop: {exc}")

        for _ in range(poll_interval):
            if _stop_event.is_set():
                break
            time.sleep(1)

    logger.info("Background worker loop stopped cleanly.")


def start_background_scheduler(poll_interval=None):
    """
    Spawns the continuous background thread if not already running.
    """
    global _scheduler_thread, _stop_event
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            logger.info("Scheduler thread is already running.")
            return

        interval = poll_interval or getattr(settings, 'SCHEDULER_POLL_INTERVAL_SECONDS', 60)
        _stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=continuous_worker_loop,
            args=(interval,),
            name="PitchSchedulerDaemon",
            daemon=True
        )
        _scheduler_thread.start()
        logger.info(f"Started continuous background scheduler thread (interval={interval}s).")


def stop_background_scheduler():
    """
    Signals the continuous background thread to terminate.
    """
    global _scheduler_thread, _stop_event
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            logger.info("Signaling background scheduler thread to stop...")
            _stop_event.set()
            _scheduler_thread.join(timeout=3)
            logger.info("Background scheduler thread stopped.")
