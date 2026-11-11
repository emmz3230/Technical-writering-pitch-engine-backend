from django.core.management.base import BaseCommand
from pitch_api.scheduler import continuous_worker_loop


class Command(BaseCommand):
    help = 'Runs the continuous background scheduler worker checking the 20-minute interval queue every 60 seconds.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Polling interval in seconds (default: 60)'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        self.stdout.write(self.style.SUCCESS(f"Starting Pitch Engine Background Scheduler (poll every {interval}s)..."))
        try:
            continuous_worker_loop(poll_interval=interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Scheduler stopped by keyboard interrupt."))
