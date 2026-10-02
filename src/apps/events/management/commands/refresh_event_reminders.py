from django.core.management.base import BaseCommand

from apps.content.models import Note
from apps.events.reminders import refresh_reminder


class Command(BaseCommand):
    help = (
        "Recompute Note.remind_at for every alive note - run once after deploying the calendar "
        "(existing documents have no remind_at yet) and after changing EVENTS_DOCUMENT_REMIND_DAYS."
    )

    def handle(self, *args, **options):
        scheduled = 0
        for note in Note.objects.alive().select_related("owner").iterator():
            if refresh_reminder(note) is not None:
                scheduled += 1
        self.stdout.write(self.style.SUCCESS(f"{scheduled} note(s) have an upcoming reminder."))
