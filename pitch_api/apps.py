import sys
import os
from django.apps import AppConfig


class PitchApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pitch_api'

    def ready(self):
        # Auto-start scheduler thread when running development server
        if 'runserver' in sys.argv:
            # Django runserver spawns two processes with the auto-reloader;
            # run scheduler only in the active worker process (RUN_MAIN == 'true')
            if os.environ.get('RUN_MAIN') == 'true':
                from .scheduler import start_background_scheduler
                start_background_scheduler()
