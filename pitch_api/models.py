from django.db import models
from django.utils import timezone
import datetime
from django.conf import settings


class WorkerState(models.Model):
    """
    Singleton state model to monitor and control background dispatching.
    Allows frontend instant 'Pause Queue', daily pitch limit enforcement,
    and automatic daily generation with rollover of unsent leads.
    """
    is_paused = models.BooleanField(default=False)
    daily_sent_count = models.PositiveIntegerField(default=0)
    last_reset_date = models.DateField(default=datetime.date.today)
    last_poll_time = models.DateTimeField(null=True, blank=True)
    last_run_status = models.CharField(max_length=120, default='Idle')
    auto_generate_daily = models.BooleanField(default=True, help_text="Automatically generate fresh 30-lead queue on date rollover")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Worker State"
        verbose_name_plural = "Worker State"

    @classmethod
    def get_state(cls):
        state, _ = cls.objects.get_or_create(id=1)
        today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
        reset_date = state.last_reset_date
        if isinstance(reset_date, datetime.datetime):
            reset_date = reset_date.date()

        if reset_date < today:
            state.daily_sent_count = 0
            state.last_reset_date = today
            state.save()
        return state

    def can_send_today(self, max_limit=30):
        today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
        reset_date = self.last_reset_date
        if isinstance(reset_date, datetime.datetime):
            reset_date = reset_date.date()

        if reset_date < today:
            self.daily_sent_count = 0
            self.last_reset_date = today
            self.save(update_fields=['daily_sent_count', 'last_reset_date'])
        return self.daily_sent_count < max_limit

    def increment_daily_count(self):
        self.daily_sent_count += 1
        self.save(update_fields=['daily_sent_count', 'updated_at'])

    def __str__(self):
        paused_str = "PAUSED" if self.is_paused else "RUNNING"
        return f"WorkerState [{paused_str}] - Sent Today: {self.daily_sent_count}/{getattr(settings, 'DAILY_PITCH_LIMIT', 30)}"


class Lead(models.Model):
    """
    Lead in the 20-minute interval scheduled pitch queue.
    """
    STATUS_CHOICES = (
        ('queued', 'Queued'),
        ('sent', 'Sent Successfully'),
        ('failed', 'Failed'),
    )

    COUNTRY_CHOICES = (
        ('US', 'United States'),
        ('UK', 'United Kingdom'),
        ('CA', 'Canada'),
        ('AU', 'Australia'),
        ('IE', 'Ireland'),
        ('NZ', 'New Zealand'),
    )

    batch_id = models.CharField(max_length=64, blank=True, db_index=True)
    company_name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True, default='Technical Documentation Team')
    contact_email = models.EmailField()
    country = models.CharField(max_length=10, choices=COUNTRY_CHOICES, default='US')
    doc_url = models.URLField(max_length=500)

    # Google Style Guide Audit fields
    documentation_snippet = models.TextField(
        blank=True, 
        help_text="Excerpt scraped from documentation where passive voice was identified."
    )
    passive_voice_violations = models.JSONField(
        default=list, 
        blank=True, 
        help_text="List of passive constructions detected with suggested active revisions."
    )
    audit_hook = models.TextField(
        blank=True, 
        help_text="Custom hook pointing directly to the Google Style Guide passive voice audit."
    )

    # Generated pitch content
    subject = models.CharField(max_length=300)
    body = models.TextField()

    # Queue & Timing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    scheduled_send_time = models.DateTimeField(db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    is_rollover = models.BooleanField(default=False, help_text="True if this lead was rolled over from an unsent or failed previous run")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_send_time', 'id']

    def __str__(self):
        return f"{self.company_name} ({self.country}) - [{self.status.upper()}] @ {self.scheduled_send_time}"
