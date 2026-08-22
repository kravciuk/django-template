import datetime

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.common.models import DEFAULT_TRASH_RETENTION_DAYS, SoftDeleteModel


class Command(BaseCommand):
    help = "Permanently delete trashed records past the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=None,
            help="Retention window in days (default: settings.TRASH_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be purged without deleting anything.",
        )

    def handle(self, *args, **options):
        retention_days = options["older_than"]
        if retention_days is None:
            retention_days = getattr(settings, "TRASH_RETENTION_DAYS", DEFAULT_TRASH_RETENTION_DAYS)
        cutoff = timezone.now() - datetime.timedelta(days=retention_days)
        dry_run = options["dry_run"]

        # Discover every soft-deletable concrete model automatically, so a
        # new package that mixes in SoftDeleteModel gets purge support for
        # free, without editing this command.
        models = sorted(
            (m for m in apps.get_models() if issubclass(m, SoftDeleteModel) and not m._meta.abstract),
            key=lambda m: m._meta.label,
        )

        if not models:
            self.stdout.write("No soft-deletable models found.")
            return

        total = 0
        for model in models:
            count = model.purge_stale(cutoff, dry_run=dry_run)
            total += count
            verb = "would purge" if dry_run else "purged"
            self.stdout.write(f"{model._meta.label}: {verb} {count} row(s)")

        verb = "Would purge" if dry_run else "Purged"
        self.stdout.write(self.style.SUCCESS(f"{verb} {total} row(s) total (cutoff: {cutoff.isoformat()})"))
