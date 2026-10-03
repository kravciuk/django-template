"""Signals for note changes that bypass Model.save() (and so post_save):
trash/restore stamp whole subtrees with queryset .update(). Sent by
apps.content.services; `pks` is the list of affected Note pks. Lets other
apps (apps.events' Google sync) react without apps.content knowing them.
"""
from django.dispatch import Signal

notes_trashed = Signal()
notes_restored = Signal()
