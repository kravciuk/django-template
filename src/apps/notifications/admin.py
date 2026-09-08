from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.translation import gettext as _

from .enums import NotificationKind
from .forms import SendNotificationForm
from .models import Notification
from .services import notify


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "sender", "kind", "is_read", "created_at")
    list_filter = ("kind", "is_read")
    search_fields = ("recipient__username", "sender__username")
    readonly_fields = ("created_at", "updated_at", "read_at")
    autocomplete_fields = ("recipient", "sender")
    change_list_template = "admin/notifications/notification/change_list.html"

    def get_urls(self):
        # Prepended so it's matched before the built-in <path:object_id>/
        # patterns further down the list - those would otherwise swallow
        # "send/" as if it were a pk.
        custom_urls = [
            path(
                "send/",
                self.admin_site.admin_view(self.send_view),
                name="notifications_notification_send",
            ),
        ]
        return custom_urls + super().get_urls()

    def send_view(self, request):
        if request.method == "POST":
            form = SendNotificationForm(request.POST)
            if form.is_valid():
                notify(
                    form.cleaned_data["recipient"],
                    kind=NotificationKind.MESSAGE,
                    payload={
                        "title": form.cleaned_data["title"],
                        "body": form.cleaned_data["body"],
                    },
                    sender=request.user,
                )
                self.message_user(
                    request,
                    _("Notification sent to %(recipient)s.")
                    % {"recipient": form.cleaned_data["recipient"]},
                    messages.SUCCESS,
                )
                return redirect("admin:notifications_notification_changelist")
        else:
            form = SendNotificationForm()

        context = {
            **self.admin_site.each_context(request),
            "title": _("Send notification"),
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/notifications/notification/send_notification.html", context)
