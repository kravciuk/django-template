from allauth.account.adapter import DefaultAccountAdapter
from constance import config


class AccountAdapter(DefaultAccountAdapter):
    """Gate registration behind the ACCOUNT_ALLOW_SIGNUP constance flag
    (core/settings/constance.py) - runtime-editable from
    /admin/constance/config/ without a redeploy.

    Registration is closed by default - see docs/future/multi-user-migration.md
    for what should be addressed before it's opened for real.
    """

    def is_open_for_signup(self, request):
        return config.ACCOUNT_ALLOW_SIGNUP
