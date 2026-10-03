from django.core.management.base import BaseCommand, CommandError

from apps.events.google.sync import sync_account
from apps.events.models import GoogleCalendarAccount


class Command(BaseCommand):
    help = "Run a Google Calendar sync now (e.g. in dev, where no Celery worker runs the scheduled one)."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="Only this username (default: every active account).")
        parser.add_argument("--full", action="store_true", help="Full resync: list all events, re-diff every link.")

    def handle(self, *args, **options):
        accounts = GoogleCalendarAccount.objects.filter(status=GoogleCalendarAccount.Status.ACTIVE).select_related("user")
        if options["user"]:
            accounts = accounts.filter(user__username=options["user"])
            if not accounts.exists():
                raise CommandError(f"No active Google Calendar account for user {options['user']!r}")
        for account in accounts:
            result = sync_account(account, full=options["full"])
            outcome = result.summary() if result else "skipped (locked or no calendar selected)"
            self.stdout.write(f"{account.user}: {outcome}")
            if result and result.errors:
                for error in result.errors[:20]:
                    self.stdout.write(f"  ! {error}")
