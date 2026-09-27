"""Data-only migration - no schema change to apps.users itself.

Backfills allauth's own account_emailaddress table (added by
allauth.account's migrations, depended on below) so every existing user with
a non-empty email keeps working once ACCOUNT_EMAIL_VERIFICATION="mandatory"
takes effect (core/settings/auth.py) - otherwise the current owner couldn't
log in by email and would be asked to (re)verify an address nobody sent them
a confirmation link for. See docs/known-issues.md KI-9 and
docs/future/multi-user-migration.md §7.
"""

from django.db import migrations


def backfill_email_addresses(apps, schema_editor):
    User = apps.get_model("users", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    for user in User.objects.exclude(email="").exclude(email__isnull=True):
        EmailAddress.objects.get_or_create(
            user=user,
            email=user.email,
            defaults={"verified": True, "primary": True},
        )


def noop_reverse(apps, schema_editor):
    # Deliberately not deleting the EmailAddress rows on reverse - a
    # migration rollback shouldn't lock existing users out of allauth-based
    # login by silently un-verifying/removing their email again.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
        ("account", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_email_addresses, noop_reverse),
    ]
