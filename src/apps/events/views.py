from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from .services import SOURCE_DOCUMENT, SOURCE_NOTE, default_color


class CalendarView(LoginRequiredMixin, TemplateView):
    template_name = "events/calendar.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["user_time_zone"] = timezone.get_current_timezone_name()
        context["has_profile_time_zone"] = bool(self.request.user.timezone)
        context["note_color"] = default_color(SOURCE_NOTE)
        context["document_color"] = default_color(SOURCE_DOCUMENT)
        return context
