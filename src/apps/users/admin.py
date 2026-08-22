from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    readonly_fields = DjangoUserAdmin.readonly_fields + (
        "registration_date",
        "registration_ip",
        "last_login_date",
        "last_login_ip",
    )
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Registration / login metadata",
            {
                "fields": (
                    "json_data",
                    "registration_date",
                    "registration_ip",
                    "last_login_date",
                    "last_login_ip",
                )
            },
        ),
    )
