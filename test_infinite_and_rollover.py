import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from pitch_api.models import Lead, WorkerState
from pitch_api.audit_engine import prepare_daily_batch

print("--- TESTING ENDLESS LEAD GENERATION & ROLLOVER ---")

# Step 1: Run prepare_daily_batch with rollover
batch = prepare_daily_batch(count=30, include_rollover=True)
rollover_count = sum(1 for l in batch if l.is_rollover)
new_count = len(batch) - rollover_count

print(f"Total leads prepared: {len(batch)}")
print(f"Rolled over from previous unsent/failed: {rollover_count}")
print(f"Brand-new unique leads generated: {new_count}")

first = batch[0]
last = batch[-1]
diff_mins = (last.scheduled_send_time - first.scheduled_send_time).total_seconds() / 60
print(f"First lead: {first.company_name} @ {first.scheduled_send_time.strftime('%H:%M:%S')} (Rollover: {first.is_rollover})")
print(f"Last lead:  {last.company_name} @ {last.scheduled_send_time.strftime('%H:%M:%S')} (Rollover: {last.is_rollover})")
print(f"Total spacing between first and last: {diff_mins:.0f} minutes across {len(batch)} leads.")

print("\nSample leads in batch:")
for l in batch[:5]:
    print(f" - [{l.country}] {l.company_name} | Rollover: {l.is_rollover} | Scheduled: {l.scheduled_send_time.strftime('%H:%M:%S')} | Retries: {l.retry_count}")

# Verify total in database
total_db = Lead.objects.count()
print(f"\nTotal leads in DB now: {total_db}")
