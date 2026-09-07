from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Comment


class CommentForm(forms.ModelForm):
    """Public-facing comment/reply/edit composer - the ONLY user-editable
    surface. target (content_type/object_id), parent, owner and ip are all
    set server-side in apps.comments.views, never bound to this form, so a
    submitted request body can't forge who posted, what it's attached to,
    or fake a parent/depth.
    """

    class Meta:
        model = Comment
        fields = ["body"]
        labels = {"body": _("Comment")}
        help_texts = {
            "body": _("Markdown is supported (e.g. **bold**, _italic_, `code`, > quotes, lists)."),
        }
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": _("Write a comment..."), "class": "form-control"}),
        }
