# The real implementation lives in libs.utils (a generic helper, not
# users-specific) so apps.comments can reuse it without an app-to-app
# import. Re-exported here so apps/users/signals.py keeps working unchanged.
from libs.utils import get_client_ip  # noqa: F401
