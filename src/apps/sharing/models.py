import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from apps.common.models import OwnedModel, TimeStampedModel


def generate_share_token():
    """A callable, not a call: passed as the field default so Django stores
    it as-is in the migration and re-invokes it per row, instead of baking
    one fixed token in for every row."""
    return secrets.token_urlsafe(32)


class ShareLink(TimeStampedModel, OwnedModel):
    """A generated, revocable link granting access to one object regardless
    of its own Visibility. Visibility.SHARED means "only reachable through
    one of these" - see apps.sharing.access.can_view.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    token = models.CharField(max_length=64, unique=True, default=generate_share_token, editable=False)
    password = models.CharField(max_length=128, blank=True)  # hashed, never stored plain
    expires_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    comment = models.CharField(max_length=255, blank=True, help_text="Who this link was issued to, and why.")

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"ShareLink({self.token[:8]}... -> {self.content_type_id}:{self.object_id})"

    def set_password(self, raw_password):
        self.password = make_password(raw_password) if raw_password else ""

    def check_password(self, raw_password):
        if not self.password:
            return True  # no password required
        return check_password(raw_password, self.password)

    @property
    def has_password(self):
        return bool(self.password)

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        if self.max_uses is not None and self.used_count >= self.max_uses:
            return False
        return True

    def register_use(self):
        self.used_count = models.F("used_count") + 1
        self.last_used_at = timezone.now()
        self.save(update_fields=["used_count", "last_used_at"])
        self.refresh_from_db(fields=["used_count"])
