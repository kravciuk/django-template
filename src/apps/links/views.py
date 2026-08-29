from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .models import LinkGroup


class LinksHomeView(LoginRequiredMixin, TemplateView):
    template_name = "links/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["groups"] = (
            LinkGroup.objects.filter(owner=self.request.user)
            .order_by("order", "id")
            .prefetch_related("links")
        )
        return context
