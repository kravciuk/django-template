from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Attachment


@receiver(post_delete, sender=Attachment)
def delete_file_from_disk(sender, instance, **kwargs):
    """Django never removes the underlying file when a row is deleted -
    this does it. Fires for any hard delete: purge_trash, the admin's
    "permanently delete" action, or a cascading delete from a deleted Note.
    save=False - we're not persisting a model instance that no longer
    exists in the database.
    """
    if instance.file:
        instance.file.delete(save=False)
