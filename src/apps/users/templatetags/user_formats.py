"""Date/time filters that follow the user's profile display formats
(apps.users.formats) instead of a fixed Django format name:

    {{ note.created_at|user_datetime }}
    {{ note.starts_at|utc|user_date }}

Same input handling as Django's own `date` filter (time zone conversion,
empty value -> "").
"""
from django import template
from django.template.defaultfilters import date as date_filter

from apps.users.formats import active_display_formats

register = template.Library()


@register.filter(expects_localtime=True, is_safe=False)
def user_date(value):
    return date_filter(value, active_display_formats().date)


@register.filter(expects_localtime=True, is_safe=False)
def user_datetime(value):
    return date_filter(value, active_display_formats().datetime)


@register.filter(expects_localtime=True, is_safe=False)
def user_time(value):
    return date_filter(value, active_display_formats().time)
