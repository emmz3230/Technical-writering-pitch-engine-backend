"""
Google Developer Documentation Style Guide Audit Engine & Scraper.
Features:
1. Curated company discovery with published contact emails and documentation issues
   verified from each company's own public website.
2. Intelligent Rollover & Resend of unsent or failed leads from previous runs.
3. Documentation scraper & passive voice auditor (Google Style Guide: Active Voice).
4. Tailored cold pitch synthesizer directly injecting passive voice violations.
"""

import re
import uuid
import random
import logging
import requests
from bs4 import BeautifulSoup
from datetime import timedelta
from urllib.parse import urljoin, urlsplit
from django.utils import timezone
from .models import Lead, WorkerState

logger = logging.getLogger(__name__)

# Target global English-speaking markets
ALLOWED_COUNTRIES = ['US', 'UK', 'CA', 'AU', 'IE', 'NZ']
ROLE_EMAIL_NAMES = {
    'contact', 'hello', 'info', 'sales', 'marketing', 'partnerships',
    'business', 'support', 'developers', 'developer-relations', 'devrel',
    'docs', 'documentation', 'community', 'team',
}
EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+"
)

# Passive voice grammatical patterns: form of "to be" + past participle
PASSIVE_PATTERNS = [
    re.compile(r'\b(is|are|was|were|be|been|being)\s+([a-zA-Z]+(?:ed|en|wn|pt|ght|lt))\b(?:\s+by\s+([a-zA-Z0-9_\-\s]{2,20}))?', re.IGNORECASE),
    re.compile(r'\b(has|have|had)\s+been\s+([a-zA-Z]+(?:ed|en|wn|pt|ght|lt))\b', re.IGNORECASE),
    re.compile(r'\b(can|could|should|must|will|would)\s+be\s+([a-zA-Z]+(?:ed|en|wn|pt|ght|lt))\b', re.IGNORECASE),
]

# Irregular past participles common in technical writing
IRREGULAR_PARTICIPLES = {
    'written', 'sent', 'built', 'found', 'made', 'kept', 'set', 'run', 
    'read', 'given', 'taken', 'chosen', 'known', 'shown', 'thrown', 'drawn'
}

# Expansive tech seed pools across categories and countries
TECH_CATALOG = {
    "AI_ML": [
        {"name": "Pinecone Vector Systems", "domain": "pinecone.io", "country": "US", "lead": "Bob van Luijt", "path": "/docs/guides/index-management"},
        {"name": "Weaviate DB", "domain": "weaviate.io", "country": "US", "lead": "Etienne Dilocker", "path": "/developers/weaviate/quickstart"},
        {"name": "Chroma Core AI", "domain": "trychroma.com", "country": "US", "lead": "Jeff Huber", "path": "/docs/embeddings/overview"},
        {"name": "Cohere Intelligence", "domain": "cohere.com", "country": "CA", "lead": "Aidan Gomez", "path": "/docs/embed-api/reference"},
        {"name": "Modal Labs Cloud", "domain": "modal.com", "country": "US", "lead": "Erik Bernhardsson", "path": "/docs/guide/serverless-gpu"},
        {"name": "Baseten Deployments", "domain": "baseten.co", "country": "US", "lead": "Tuhin Srivastava", "path": "/docs/model-deployment/triton"},
        {"name": "OctoAI Inference", "domain": "octoai.cloud", "country": "US", "lead": "Luis Ceze", "path": "/docs/compute/endpoints"},
        {"name": "Together Computer", "domain": "together.ai", "country": "US", "lead": "Vipul Ved Prakash", "path": "/docs/inference/getting-started"},
        {"name": "Groq Accelerator Systems", "domain": "groq.com", "country": "US", "lead": "Jonathan Ross", "path": "/docs/lpu-architecture"},
        {"name": "Synthesia UK", "domain": "synthesia.io", "country": "UK", "lead": "Victor Riparbelli", "path": "/docs/api-reference/avatars"},
        {"name": "Speechmatics Cambridge", "domain": "speechmatics.com", "country": "UK", "lead": "Katy Wigdahl", "path": "/docs/speech-api/transcribe"},
        {"name": "ElevenLabs London", "domain": "elevenlabs.io", "country": "UK", "lead": "Mati Staniszewski", "path": "/docs/api-reference/voice-generation"},
        {"name": "Unstructured IO CA", "domain": "unstructured.io", "country": "CA", "lead": "Brian Raymond", "path": "/docs/api-reference/partition"},
        {"name": "Appen Technology AU", "domain": "appen.com", "country": "AU", "lead": "Ryan Brandeburg", "path": "/docs/annotation/platform"},
        {"name": "Leonardo Interactive AU", "domain": "leonardo.ai", "country": "AU", "lead": "JJ Fiasson", "path": "/docs/generation-api"},
        {"name": "Soul Machines Auckland", "domain": "soulmachines.com", "country": "NZ", "lead": "Mark Sagar", "path": "/docs/digital-dna/sdk"},
    ],
    "DEVTOOLS_CLOUD": [
        {"name": "Supabase Inc.", "domain": "supabase.com", "country": "US", "lead": "Ant Wilson", "path": "/docs/guides/database/overview"},
        {"name": "Vercel Edge Platform", "domain": "vercel.com", "country": "US", "lead": "Lee Robinson", "path": "/docs/functions/serverless-functions"},
        {"name": "Fly.io Cloud", "domain": "fly.io", "country": "US", "lead": "Kurt Mackey", "path": "/docs/machines/overview"},
        {"name": "Railway App", "domain": "railway.com", "country": "US", "lead": "Jake Cooper", "path": "/docs/databases/postgresql"},
        {"name": "Render Cloud Services", "domain": "render.com", "country": "US", "lead": "Anurag Goel", "path": "/docs/web-services"},
        {"name": "Pulumi Infrastructure", "domain": "pulumi.com", "country": "US", "lead": "Joe Duffy", "path": "/docs/concepts/resources"},
        {"name": "Tailscale Networking", "domain": "tailscale.com", "country": "CA", "lead": "Avery Pennarun", "path": "/kb/1017/install"},
        {"name": "1Password Developer Platform", "domain": "1password.com", "country": "CA", "lead": "Jeff Shiner", "path": "/docs/cli/secrets"},
        {"name": "Shopify Developer Tools", "domain": "shopify.dev", "country": "CA", "lead": "Tobi Lutke", "path": "/docs/apps/architecture"},
        {"name": "Cloudflare Workers UK", "domain": "cloudflare.com", "country": "UK", "lead": "Matthew Prince", "path": "/workers/runtime-apis/handlers"},
        {"name": "Thought Machine Vault UK", "domain": "thoughtmachine.net", "country": "UK", "lead": "Paul Taylor", "path": "/docs/vault-core/smart-contracts"},
        {"name": "Atlassian Sydney", "domain": "atlassian.com", "country": "AU", "lead": "Mike Cannon-Brookes", "path": "/cloud/jira/platform/rest/v3/intro"},
        {"name": "Canva Developer SDK AU", "domain": "canva.dev", "country": "AU", "lead": "Melanie Perkins", "path": "/docs/apps/getting-started"},
        {"name": "Octopus Deploy Brisbane", "domain": "octopus.com", "country": "AU", "lead": "Paul Stovell", "path": "/docs/api/deployments"},
        {"name": "Buildkite Melbourne", "domain": "buildkite.com", "country": "AU", "lead": "Keith Pitt", "path": "/docs/pipelines/agent"},
        {"name": "Intercom Dublin Platform", "domain": "intercom.com", "country": "IE", "lead": "Eoghan McCabe", "path": "/docs/references/rest-api"},
        {"name": "Teamwork Cork Systems", "domain": "teamwork.com", "country": "IE", "lead": "Peter Coppinger", "path": "/apidocs/tasks/v3"},
        {"name": "Workhuman Engineering Dublin", "domain": "workhuman.com", "country": "IE", "lead": "Eric Mosley", "path": "/developers/rest-api"},
        {"name": "Xero Developer Cloud NZ", "domain": "xero.com", "country": "NZ", "lead": "Rod Drury", "path": "/documentation/api/accounting"},
        {"name": "Pushpay Auckland Systems", "domain": "pushpay.com", "country": "NZ", "lead": "Molly Matthews", "path": "/developer/api/transactions"},
        {"name": "Vend by Lightspeed Auckland", "domain": "vendhq.com", "country": "NZ", "lead": "Vaughan Rowsell", "path": "/docs/register/sync"},
        {"name": "Timely Cloud Auckland", "domain": "gettimely.com", "country": "NZ", "lead": "Ryan Baker", "path": "/developer/api/appointments"},
        {"name": "Halter AgTech NZ", "domain": "halterhq.com", "country": "NZ", "lead": "Craig Piggott", "path": "/technology/telemetry/lora"},
    ],
    "FINTECH_PAYMENTS": [
        {"name": "Stripe Payments US", "domain": "stripe.com", "country": "US", "lead": "Patrick Collison", "path": "/docs/api/payment_intents"},
        {"name": "Plaid Technologies", "domain": "plaid.com", "country": "US", "lead": "Zach Perret", "path": "/docs/api/tokens"},
        {"name": "Modern Treasury", "domain": "moderntreasury.com", "country": "US", "lead": "Dimitri Dadiomov", "path": "/docs/api/transfers"},
        {"name": "Lithic Card Issuing", "domain": "lithic.com", "country": "US", "lead": "Bo Jiang", "path": "/docs/api/cards"},
        {"name": "Revolut Business London", "domain": "revolut.com", "country": "UK", "lead": "Nik Storonsky", "path": "/docs/business/business-api"},
        {"name": "GoCardless Payments UK", "domain": "gocardless.com", "country": "UK", "lead": "Hiroki Takeuchi", "path": "/api-reference/mandates"},
        {"name": "Wealthsimple Toronto", "domain": "wealthsimple.com", "country": "CA", "lead": "Michael Katchen", "path": "/developer/api/investing"},
        {"name": "Airwallex Melbourne", "domain": "airwallex.com", "country": "AU", "lead": "Jack Zhang", "path": "/docs/api/transfers"},
        {"name": "Fenergo Compliance Dublin", "domain": "fenergo.com", "country": "IE", "lead": "Marc Murphy", "path": "/solutions/clm/api"},
        {"name": "Flipdish Dublin Order Systems", "domain": "flipdish.com", "country": "IE", "lead": "Conor McCarthy", "path": "/developer/api/orders"},
    ],
    "CYBERSECURITY_IDENTITY": [
        {"name": "Clerk Auth US", "domain": "clerk.com", "country": "US", "lead": "Colin Sidoti", "path": "/docs/quickstarts/nextjs"},
        {"name": "WorkOS Enterprise SSO", "domain": "workos.com", "country": "US", "lead": "Michael Grinich", "path": "/docs/sso/guide"},
        {"name": "Stytch Identity Systems", "domain": "stytch.com", "country": "US", "lead": "Reed McGinley-Stempel", "path": "/docs/magic-links/email"},
        {"name": "Onfido Identity London", "domain": "onfido.com", "country": "UK", "lead": "Husayn Kassai", "path": "/documentation/api/applicants"},
        {"name": "Kinde Auth Sydney", "domain": "kinde.com", "country": "AU", "lead": "Ross Chaldecott", "path": "/docs/developer-tools/sdks"},
        {"name": "SafetyCulture Sydney Auth", "domain": "safetyculture.com", "country": "AU", "lead": "Luke Anear", "path": "/reference/inspections"},
    ]
}

# Documentation snippet patterns containing authentic passive voice structures
DOC_SNIPPET_TEMPLATES = [
    "When incoming payloads are received by the webhook listener, signatures are validated against your secret key.",
    "Serverless functions are scaled automatically by our edge container cluster. Requests are routed to the nearest regional worker.",
    "Authentication tokens must be generated via the OAuth token endpoint. All requests are authenticated with a Bearer header.",
    "Database records are updated atomically whenever payment events are submitted by your application client.",
    "Telemetry metrics and error traces are collected continuously by the background agent daemon.",
    "A new payment intent is created when the checkout flow is initiated. Funds are captured once authorized by the bank.",
    "API rate limits are calculated dynamically based on plan tier. Excess requests are throttled with HTTP 429.",
    "Encryption keys are managed securely by hardware security modules. Plaintext data is never logged to disk.",
    "Bulk ingestion jobs are processed asynchronously in the queue. Completion webhooks are dispatched to your server.",
    "Audit logs are generated for every administrative mutation. Logs can be exported to S3 or BigQuery destinations.",
    "Custom domain certificates are renewed automatically by the certificate manager prior to expiration.",
    "Session cookies are signed cryptographically using HMAC SHA-256. Expired sessions are purged periodically.",
]

def generate_infinite_company_pool(needed_count=30, exclude_names=None):
    """
    Returns only unpitched companies from the curated catalog. Never invents companies,
    domains, contact names, or email addresses.
    """
    exclude = set(exclude_names or [])
    pool = []

    # Return only companies from the explicitly curated catalog.
    catalog_items = []
    for cat_items in TECH_CATALOG.values():
        catalog_items.extend(cat_items)

    random.shuffle(catalog_items)
    for item in catalog_items:
        if item["name"] not in exclude:
            pool.append({
                "company_name": item["name"],
                "contact_name": "Documentation Team",
                "contact_email": "",
                "country": item["country"],
                "domain": item["domain"],
                "doc_url": f"https://{item['domain']}{item['path']}",
            })
            exclude.add(item["name"])
            if len(pool) >= needed_count:
                return pool

    return pool


def _is_company_host(hostname, company_domain):
    hostname = (hostname or '').lower().rstrip('.')
    company_domain = company_domain.lower().rstrip('.')
    return hostname == company_domain or hostname.endswith(f'.{company_domain}')


def _role_email_candidates(emails, company_domain):
    candidates = set()
    for email in emails:
        local_part, separator, email_domain = email.lower().rpartition('@')
        if not separator or not _is_company_host(email_domain, company_domain):
            continue
        role_name = re.sub(r'\+.*$', '', local_part)
        if role_name in ROLE_EMAIL_NAMES:
            candidates.add(email.lower())
    return candidates


def discover_public_contact_email(domain, doc_url):
    """Find a role-based email explicitly published on the company's own website."""
    page_urls = [f"https://{domain}", doc_url]
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; TechnicalDocumentationAudit/1.0)',
        'Accept': 'text/html,application/xhtml+xml'
    }
    visited = set()
    contact_pages = []
    emails = set()

    def collect_page(url):
        parsed_url = urlsplit(url)
        if not _is_company_host(parsed_url.hostname, domain) or url in visited:
            return
        visited.add(url)
        try:
            page = requests.get(url, headers=headers, timeout=3)
        except requests.RequestException as exc:
            logger.info("Contact discovery request failed for %s: %s", url, exc)
            return

        final_url = urlsplit(page.url or url)
        if not _is_company_host(final_url.hostname, domain) or page.status_code != 200:
            return
        content_type = page.headers.get('Content-Type', '')
        if content_type and 'html' not in content_type.lower():
            return

        soup = BeautifulSoup(page.text, 'html.parser')
        for anchor in soup.select('a[href]'):
            href = anchor.get('href', '').strip()
            if href.lower().startswith('mailto:'):
                emails.update(EMAIL_PATTERN.findall(href[7:].split('?', 1)[0]))
                continue
            absolute_url = urljoin(page.url or url, href)
            path = urlsplit(absolute_url).path.lower()
            if (
                _is_company_host(urlsplit(absolute_url).hostname, domain)
                and re.search(r'contact|about|support|company', path)
            ):
                contact_pages.append(absolute_url)

        emails.update(EMAIL_PATTERN.findall(soup.get_text(' ', strip=True)))

    for url in page_urls:
        collect_page(url)
        if _role_email_candidates(emails, domain):
            break

    for url in contact_pages:
        if len(visited) >= 4:
            break
        collect_page(url)
        if _role_email_candidates(emails, domain):
            break

    candidates = _role_email_candidates(emails, domain)
    return sorted(candidates)[0] if candidates else ''


def scrape_documentation(url):
    """
    Scrapes actual documentation text. Returns empty when the page cannot be verified.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        resp = requests.get(url, headers=headers, timeout=4)
    except requests.RequestException as exc:
        logger.info("Documentation request failed for %s: %s", url, exc)
        return ''

    if resp.status_code != 200:
        return ''

    soup = BeautifulSoup(resp.text, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'noscript', 'svg']):
        tag.decompose()

    main_content = soup.find('article') or soup.find('main') or soup.find('div', role='main') or soup.body
    if not main_content:
        return ''
    return re.sub(r'\s+', ' ', main_content.get_text(separator=' ', strip=True))[:4000]


def audit_passive_voice(text):
    """
    Audits documentation text according to the Google Developer Documentation Style Guide rule:
    'Use active voice rather than passive voice.'
    """
    violations = []
    sentences = re.split(r'(?<=[.!?])\s+', text)

    for sentence in sentences:
        sentence_clean = sentence.strip()
        if len(sentence_clean) < 15:
            continue

        for pattern in PASSIVE_PATTERNS:
            match = pattern.search(sentence_clean)
            if match:
                passive_phrase = match.group(0).strip()
                verb = match.group(2).lower()
                agent = match.group(3).strip() if (match.lastindex and match.lastindex >= 3 and match.group(3)) else None

                if agent:
                    suggestion = f"Rewrite actively: '{agent} {verb}s...' instead of '{passive_phrase}'"
                else:
                    suggestion = f"Identify the actor and rephrase actively: e.g., 'The system {verb}s...' instead of '{passive_phrase}'"

                violations.append({
                    "sentence": sentence_clean,
                    "passive_phrase": passive_phrase,
                    "rule": "Google Style Guide: Active Voice",
                    "suggestion": suggestion,
                })
                break

        if len(violations) >= 3:
            break

    return violations


def synthesize_pitch(company_name, contact_name, violations, variation=0):
    """
    Creates a conversational, personalized introduction using the audit finding.
    """
    if not violations:
        raise ValueError("A verified documentation issue is required to create a pitch.")
    v = violations[0]

    hook_snippet = (
        f"Example of an active-voice edit:\n"
        f"  \"{v['sentence']}\"\n"
        f"Suggested rewrite:\n"
        f"  \"{v['suggestion']}\"\n"
        "This is an illustrative example, not a measured performance claim."
    )

    subject_templates = (
        "A small suggestion for {company_name}'s developer docs",
        "Quick thought about your API documentation",
        "Could this sentence be clearer?",
        "A documentation note for {company_name}",
        "One idea for your developer docs",
    )
    body_templates = (
        """Hi {salutation},

I wanted to introduce myself. I'm a technical writer who helps teams make developer documentation easier to use.

Here's a quick example of the kind of edit I work on:
“{sentence}”
→ “{suggestion}”

If a review of {company_name}'s docs would be useful, I can take a look and send a few specific notes. Would you be open to that?

No worries if it's not a priority.

Best,
Emmanuel Samuel
emmz3230@gmail.com
https://samuel-emmanuel-technical-writer.netlify.app/""",
        """Hi {salutation},

I'm reaching out because I work with teams on their developer documentation. A simple example of an edit I often make:
“{sentence}” → “{suggestion}”

If you'd like, I could review a page from {company_name}'s docs and send back a few practical suggestions. Would that be helpful?

Best,
Technical Writing Consultant
emmz3230@gmail.com
https://samuel-emmanuel-technical-writer.netlify.app/""",
        """Hi {salutation},

Thought I'd share a small example of the kind of documentation work I do:
“{sentence}”
could become
“{suggestion}”

I'm a technical writer, and I help make docs clearer for developers. If you'd like me to take a look at {company_name}'s docs, just say the word. If not, all good.

Thanks,
Technical Writing Consultant
emmz3230@gmail.com
https://samuel-emmanuel-technical-writer.netlify.app/""",
        """Hi {salutation},

I'm a technical writing consultant, and one small example of what I help with is turning passive sentences into direct instructions:
“{sentence}” → “{suggestion}”

Would it be useful if I reviewed a page from {company_name}'s documentation and shared a few notes? Happy to keep it brief.

Best,
Technical Writing Consultant
emmz3230@gmail.com
https://samuel-emmanuel-technical-writer.netlify.app/""",
        """Hi {salutation},

Hope your week's going well. I'm reaching out to introduce my technical writing work. For example, an edit might look like this:
“{sentence}”
becomes
“{suggestion}”

If documentation improvements are on your list, I could review a page from {company_name} and send a few tailored ideas. Just let me know.

Regards,
Technical Writing Consultant
emmz3230@gmail.com
https://samuel-emmanuel-technical-writer.netlify.app/""",
    )
    variant = variation % len(body_templates)
    recipient_salutation = (
        contact_name.split()[0]
        if contact_name and "Team" not in contact_name and "Lead" not in contact_name
        else f"{company_name} team"
    )
    template_values = {
        "company_name": company_name,
        "salutation": recipient_salutation,
        "sentence": v["sentence"],
        "suggestion": v["suggestion"],
    }

    subject = subject_templates[variant].format(company_name=company_name)
    body = body_templates[variant].format(**template_values)

    return {
        "subject": subject,
        "body": body,
        "audit_hook": hook_snippet,
        "snippet": v['sentence']
    }


def get_unsent_and_failed_leads(limit=30):
    """
    Identifies leads from previous runs that were NOT successfully delivered:
    1. Leads with status='failed' (e.g. temporary SMTP timeout/error).
    2. Leads with status='queued' that were scheduled in past hours/days and never sent.
    """
    now = timezone.now()
    # Expired queued leads (scheduled more than 2 hours ago but never sent)
    stale_queued = Lead.objects.filter(
        status='queued',
        contact_email__gt='',
        scheduled_send_time__lt=now - timedelta(hours=2)
    ).exclude(contact_email__istartswith='leads-demo+')
    # Failed leads that have not yet succeeded
    failed_leads = Lead.objects.filter(status='failed', contact_email__gt='').exclude(
        contact_email__istartswith='leads-demo+'
    ).order_by('-updated_at')

    combined_ids = list(stale_queued.values_list('id', flat=True)[:limit])
    remaining_slots = limit - len(combined_ids)
    if remaining_slots > 0:
        combined_ids.extend(list(failed_leads.values_list('id', flat=True)[:remaining_slots]))

    return Lead.objects.filter(id__in=combined_ids)


def prepare_daily_batch(count=30, include_rollover=True):
    """
    Core Daily Dispatch Engine:
    1. Rollover: Automatically fetches unsent & failed leads from yesterday/earlier runs,
       resets their status to 'queued', increments retry_count, and schedules them first.
    2. Discovery: Queues only curated companies with a published role email and a verified
       documentation issue. The batch can be smaller than requested.
    3. Spacing: Schedules verified leads 20 minutes apart starting from now.
    """
    now = timezone.now()
    batch_id = str(uuid.uuid4())[:8]
    final_leads = []
    scheduled_slot = 0

    # Step 1: Rollover unsent / failed leads if requested
    if include_rollover:
        unsent_leads = list(get_unsent_and_failed_leads(limit=count))
        for lead in unsent_leads:
            scheduled_time = now + timedelta(minutes=scheduled_slot * 20)
            lead.status = 'queued'
            lead.scheduled_send_time = scheduled_time
            lead.error_message = None
            lead.retry_count += 1
            lead.is_rollover = True
            lead.batch_id = batch_id
            lead.save(update_fields=['status', 'scheduled_send_time', 'error_message', 'retry_count', 'is_rollover', 'batch_id', 'updated_at'])
            final_leads.append(lead)
            scheduled_slot += 1

            if len(final_leads) >= count:
                break

    # Step 2: Determine how many fresh new leads are needed to reach exact target (30)
    needed_new = count - len(final_leads)
    if needed_new > 0:
        WorkerState.objects.update_or_create(
            id=1,
            defaults={'last_auto_generate_date': timezone.localdate()},
        )
        # Avoid repeating companies that have a real email address on an existing lead.
        existing_companies = set(
            Lead.objects.exclude(contact_email='')
            .exclude(contact_email__istartswith='leads-demo+')
            .values_list('company_name', flat=True)
        )
        catalog_size = sum(len(items) for items in TECH_CATALOG.values())
        new_items = generate_infinite_company_pool(
            needed_count=catalog_size,
            exclude_names=existing_companies
        )

        new_leads_to_create = []
        for item in new_items:
            doc_text = scrape_documentation(item['doc_url'])
            if not doc_text:
                logger.info("Skipping %s: documentation page could not be verified.", item['company_name'])
                continue
            violations = audit_passive_voice(doc_text)
            if not violations:
                logger.info("Skipping %s: no passive-voice issue was found.", item['company_name'])
                continue
            contact_email = discover_public_contact_email(item['domain'], item['doc_url'])
            if not contact_email:
                logger.info("Skipping %s: no published role contact email was found.", item['company_name'])
                continue

            scheduled_time = now + timedelta(minutes=scheduled_slot * 20)
            pitch = synthesize_pitch(
                company_name=item['company_name'],
                contact_name=item['contact_name'],
                violations=violations,
                variation=scheduled_slot
            )

            new_lead = Lead(
                batch_id=batch_id,
                company_name=item['company_name'],
                contact_name=item['contact_name'],
                contact_email=contact_email,
                country=item['country'],
                doc_url=item['doc_url'],
                documentation_snippet=pitch['snippet'],
                passive_voice_violations=violations,
                audit_hook=pitch['audit_hook'],
                subject=pitch['subject'],
                body=pitch['body'],
                status='queued',
                scheduled_send_time=scheduled_time,
                is_rollover=False
            )
            new_leads_to_create.append(new_lead)
            scheduled_slot += 1
            if len(new_leads_to_create) >= needed_new:
                break

        Lead.objects.bulk_create(new_leads_to_create)
        final_leads.extend(new_leads_to_create)
        if len(new_leads_to_create) < needed_new:
            logger.warning(
                "Only %s of %s requested new leads had both a published role email and "
                "a verified documentation issue.",
                len(new_leads_to_create),
                needed_new,
            )

    return final_leads


def generate_lead_batch(count=30):
    """
    Standard generation endpoint wrapper with rollover enabled.
    """
    return prepare_daily_batch(count=count, include_rollover=True)
