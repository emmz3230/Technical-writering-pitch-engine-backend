import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from pitch_api.models import Lead, WorkerState
from pitch_api.scheduler import process_due_pitches, send_lead_email

state = WorkerState.get_state()
print("Initial Worker State:", state)

# Test 1: Paused behavior
state.is_paused = True
state.save()
dispatched = process_due_pitches()
print(f"When PAUSED, dispatched count: {dispatched} (Expected: 0)")
print("Status message:", state.last_run_status)

# Test 2: Resume
state.is_paused = False
state.save()
print("Worker resumed.")

# Test 3: Due lead dispatch
first_lead = Lead.objects.filter(status='queued').first()
print(f"Testing dispatch for lead: {first_lead.company_name} ({first_lead.status})")
send_lead_email(first_lead)
first_lead.refresh_from_db()
print(f"After dispatch, Lead Status: {first_lead.status} (sent_at={first_lead.sent_at}, error={first_lead.error_message})")
state.refresh_from_db()
print(f"Worker Daily Sent Count: {state.daily_sent_count}/30")
