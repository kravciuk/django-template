import hashlib


def get_client_ip(request):
    """Extract the client's IP address (IPv4 or IPv6) from a request.

    In prod, nginx proxies requests to gunicorn, so the real client address
    arrives via X-Forwarded-For; REMOTE_ADDR is used as a fallback for direct
    connections (e.g. dev runserver).
    """
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def sha256_of(fileobj, chunk_size=65536):
    """Stream `fileobj` through SHA-256 without loading it fully into memory.

    Leaves the file position wherever reading stops - callers that need to
    read the file again afterwards (e.g. Pillow for image dimensions) must
    seek(0) themselves.
    """
    digest = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(chunk_size), b""):
        digest.update(chunk)
    return digest.hexdigest()
