import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from pitch_api.audit_engine import generate_infinite_company_pool
from pitch_api.models import Lead

existing = set(Lead.objects.values_list('company_name', flat=True))
print(f"Existing companies in DB: {len(existing)}")

new_pool = generate_infinite_company_pool(needed_count=10, exclude_names=existing)
print("Newly generated fresh companies (zero duplicates):")
for c in new_pool:
    print(f" + {c['company_name']} ({c['country']}) - {c['doc_url']}")
