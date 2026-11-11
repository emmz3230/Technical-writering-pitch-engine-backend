from rest_framework import serializers
from django.conf import settings
from .models import Lead, WorkerState
from .audit_engine import get_unsent_and_failed_leads


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [
            'id',
            'batch_id',
            'company_name',
            'contact_name',
            'contact_email',
            'country',
            'doc_url',
            'documentation_snippet',
            'passive_voice_violations',
            'audit_hook',
            'subject',
            'body',
            'status',
            'scheduled_send_time',
            'sent_at',
            'error_message',
            'retry_count',
            'is_rollover',
            'created_at',
            'updated_at'
        ]


class WorkerStateSerializer(serializers.ModelSerializer):
    daily_limit = serializers.SerializerMethodField()
    remaining_today = serializers.SerializerMethodField()
    next_dispatch_time = serializers.SerializerMethodField()
    queued_count = serializers.SerializerMethodField()
    sent_count = serializers.SerializerMethodField()
    failed_count = serializers.SerializerMethodField()
    unsent_count = serializers.SerializerMethodField()

    class Meta:
        model = WorkerState
        fields = [
            'id',
            'is_paused',
            'auto_generate_daily',
            'daily_sent_count',
            'daily_limit',
            'remaining_today',
            'last_reset_date',
            'last_poll_time',
            'last_run_status',
            'next_dispatch_time',
            'queued_count',
            'sent_count',
            'failed_count',
            'unsent_count',
            'updated_at'
        ]

    def get_daily_limit(self, obj):
        return getattr(settings, 'DAILY_PITCH_LIMIT', 30)

    def get_remaining_today(self, obj):
        limit = getattr(settings, 'DAILY_PITCH_LIMIT', 30)
        return max(0, limit - obj.daily_sent_count)

    def get_next_dispatch_time(self, obj):
        next_lead = Lead.objects.filter(status='queued').order_by('scheduled_send_time').first()
        return next_lead.scheduled_send_time if next_lead else None

    def get_queued_count(self, obj):
        return Lead.objects.filter(status='queued').count()

    def get_sent_count(self, obj):
        return Lead.objects.filter(status='sent').count()

    def get_failed_count(self, obj):
        return Lead.objects.filter(status='failed').count()

    def get_unsent_count(self, obj):
        return get_unsent_and_failed_leads(limit=100).count()
