from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.translation import gettext
from django.views.generic import UpdateView

from .forms import ProfileForm


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    """Edit the fields allauth's own account pages don't cover.

    Username/email/password/2FA all live under /accounts/ (allauth) instead -
    see src/templates/allauth/ and apps/users/urls.py.
    """

    form_class = ProfileForm
    template_name = "users/profile.html"
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, gettext("Profile updated."))
        return response
