from django.test import TestCase
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from unittest.mock import Mock, patch

from .audit_engine import (
    generate_infinite_company_pool,
    get_unsent_and_failed_leads,
    discover_public_contact_email,
    prepare_daily_batch,
    audit_passive_voice,
    synthesize_pitch,
)
from .models import Lead
from .models import WorkerState
from .scheduler import check_and_auto_generate_daily_batch, send_lead_email


class ContactEmailTests(TestCase):
    def create_lead(self, email):
        return Lead.objects.create(
            company_name='Example Company',
            contact_name='Documentation Team',
            contact_email=email,
            country='US',
            doc_url='https://example.com/docs',
            subject='Documentation feedback',
            body='Test message',
            scheduled_send_time=timezone.now(),
        )

    def test_company_pool_contains_only_curated_sites_without_guessed_emails(self):
        leads = generate_infinite_company_pool(needed_count=3)

        self.assertEqual(len(leads), 3)
        self.assertTrue(all(not lead['contact_email'] for lead in leads))
        self.assertTrue(all(lead['domain'] in lead['doc_url'] for lead in leads))

    @patch('pitch_api.audit_engine.requests.get')
    def test_contact_discovery_uses_role_address_published_on_company_site(self, get):
        pages = [
            Mock(
                status_code=200,
                url='https://example.com',
                headers={'Content-Type': 'text/html'},
                text='<a href="/contact">Contact</a><a href="mailto:jane@example.com">Jane</a>',
            ),
            Mock(
                status_code=200,
                url='https://example.com/docs',
                headers={'Content-Type': 'text/html'},
                text='<main>Developer documentation</main>',
            ),
            Mock(
                status_code=200,
                url='https://example.com/contact',
                headers={'Content-Type': 'text/html'},
                text='<a href="mailto:hello@example.com">Email us</a>'
                     '<a href="mailto:info@other.example">Other contact</a>',
            ),
        ]
        get.side_effect = pages

        email = discover_public_contact_email('example.com', 'https://example.com/docs')

        self.assertEqual(email, 'hello@example.com')

    @patch('pitch_api.audit_engine.requests.get')
    def test_contact_discovery_rejects_personal_and_external_addresses(self, get):
        get.return_value = Mock(
            status_code=200,
            url='https://example.com',
            headers={'Content-Type': 'text/html'},
            text='<a href="mailto:jane@example.com">Jane</a>'
                 '<a href="mailto:info@another-company.com">Contact</a>',
        )

        email = discover_public_contact_email('example.com', 'https://example.com/docs')

        self.assertEqual(email, '')

    @patch('pitch_api.audit_engine.discover_public_contact_email')
    @patch('pitch_api.audit_engine.scrape_documentation')
    @patch('pitch_api.audit_engine.generate_infinite_company_pool')
    def test_batch_does_not_queue_without_verified_documentation_issue(
        self, generate_pool, scrape_docs, discover_email
    ):
        generate_pool.return_value = [{
            'company_name': 'Example Company',
            'contact_name': 'Documentation Team',
            'contact_email': '',
            'country': 'US',
            'domain': 'example.com',
            'doc_url': 'https://example.com/docs',
        }]
        scrape_docs.return_value = 'The service returns the response.'

        leads = prepare_daily_batch(count=1, include_rollover=False)

        self.assertEqual(leads, [])
        discover_email.assert_not_called()
        self.assertEqual(Lead.objects.count(), 0)

    @patch('pitch_api.audit_engine.discover_public_contact_email', return_value='docs@example.com')
    @patch(
        'pitch_api.audit_engine.scrape_documentation',
        return_value='The response is returned by the service.',
    )
    @patch('pitch_api.audit_engine.generate_infinite_company_pool')
    def test_batch_requires_published_email_and_stores_found_address(
        self, generate_pool, scrape_docs, discover_email
    ):
        generate_pool.return_value = [{
            'company_name': 'Example Company',
            'contact_name': 'Documentation Team',
            'contact_email': '',
            'country': 'US',
            'domain': 'example.com',
            'doc_url': 'https://example.com/docs',
        }]

        leads = prepare_daily_batch(count=1, include_rollover=False)

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].contact_email, 'docs@example.com')
        discover_email.assert_called_once_with('example.com', 'https://example.com/docs')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_missing_and_demo_addresses_are_not_sent(self):
        test_cases = (
            ('', 'real contact email'),
            ('leads-demo+flyiocloud@fly.io', 'real contact email'),
            ('not-an-email', 'invalid'),
        )
        for email, expected_error in test_cases:
            with self.subTest(email=email):
                lead = self.create_lead(email)

                self.assertFalse(send_lead_email(lead))

                lead.refresh_from_db()
                self.assertEqual(lead.status, 'failed')
                self.assertIn(expected_error, lead.error_message)
                self.assertEqual(mail.outbox, [])

    def test_failed_placeholder_leads_are_not_rolled_over(self):
        lead = self.create_lead('leads-demo+flyiocloud@fly.io')
        lead.status = 'failed'
        lead.save(update_fields=['status'])

        self.assertNotIn(lead, get_unsent_and_failed_leads())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_valid_contact_address_is_sent(self):
        lead = self.create_lead('contact@example.com')

        self.assertTrue(send_lead_email(lead))

        lead.refresh_from_db()
        self.assertEqual(lead.status, 'sent')
        self.assertEqual(mail.outbox[0].to, ['contact@example.com'])


class PitchCopyTests(TestCase):
    def test_audit_does_not_invent_a_documentation_issue(self):
        self.assertEqual(audit_passive_voice('The service returns the response.'), [])
        with self.assertRaises(ValueError):
            synthesize_pitch('Example Company', 'Documentation Team', [])

    def test_batch_variations_use_distinct_conversational_copy(self):
        pitches = [
            synthesize_pitch(
                company_name="Example Company",
                contact_name="Documentation Team",
                violations=[{
                    "sentence": "The response is returned by the service.",
                    "passive_phrase": "is returned by",
                    "suggestion": "The service returns the response.",
                }],
                variation=index,
            )
            for index in range(5)
        ]

        self.assertEqual(len({pitch["subject"] for pitch in pitches}), 5)
        self.assertEqual(len({pitch["body"] for pitch in pitches}), 5)
        self.assertTrue(all("example" in pitch["body"].lower() for pitch in pitches))
        self.assertTrue(all("Technical Writing Consultant" in pitch["body"] for pitch in pitches))


class DailyDiscoveryTests(TestCase):
    def test_empty_auto_discovery_is_not_repeated_each_scheduler_poll(self):
        state = WorkerState.objects.create(
            is_paused=False,
            auto_generate_daily=True,
            daily_sent_count=0,
            last_reset_date=timezone.localdate(),
        )
        with patch('pitch_api.scheduler.prepare_daily_batch', return_value=[]) as discover:
            check_and_auto_generate_daily_batch(state)
            check_and_auto_generate_daily_batch(state)

        self.assertEqual(discover.call_count, 1)
        state.refresh_from_db()
        self.assertEqual(state.last_auto_generate_date, timezone.localdate())
        self.assertIn('No verified prospects', state.last_run_status)
