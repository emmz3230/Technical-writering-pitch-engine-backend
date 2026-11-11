import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from pitch_api.models import Lead, WorkerState
from pitch_api.audit_engine import generate_lead_batch

Lead.objects.all().delete()
leads = generate_lead_batch(count=30)
print(f"Total Leads Created: {len(leads)}")

countries = sorted(list(set(l.country for l in leads)))
print(f"Countries Represented: {countries}")

first = leads[0]
last = leads[-1]
diff_minutes = (last.scheduled_send_time - first.scheduled_send_time).total_seconds() / 60
print(f"First Lead Scheduled: {first.company_name} ({first.country}) @ {first.scheduled_send_time.strftime('%H:%M:%S')}")
print(f"Last Lead Scheduled:  {last.company_name} ({last.country}) @ {last.scheduled_send_time.strftime('%H:%M:%S')} (Diff: {diff_minutes:.0f} mins)")

print("\n--- SAMPLE HOOK GENERATED ---")
print("Company:", first.company_name)
print("Violations:", first.passive_voice_violations[0])
print("Audit Hook:\n", first.audit_hook)
