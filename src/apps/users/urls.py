from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

app_name = "users"

urlpatterns = [
    # path("register/", views.RegisterView.as_view(), name="register"),
    # JWT: SIMPLE_JWT was configured in settings but never wired to an
    # endpoint - added here so a non-browser client (see
    # apps.notifications.ws_auth) has a way to actually obtain a token.
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
