"""Request boundaries for the two loopback-only Flask applications."""
import re
from urllib.parse import urlsplit

from flask import Flask, abort, request


LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}
LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", re.IGNORECASE)


def install_local_host_guard(app: Flask) -> None:
    @app.before_request
    def require_local_host() -> None:
        # Check before rendering / or issuing cookies. A rebound browser's
        # source address is loopback too, so remote_addr alone is insufficient.
        if not LOCAL_HOST.fullmatch(request.host):
            abort(403)


def _origin(value: str) -> tuple[str, str | None, int] | None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port
        return parsed.scheme, parsed.hostname, port if port is not None else (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def require_local_management_request() -> None:
    if request.remote_addr not in LOOPBACK_ADDRESSES:
        abort(403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("Origin")
        if origin is not None:
            supplied_origin = _origin(origin)
            if supplied_origin is None or supplied_origin != _origin(request.host_url.rstrip("/")):
                abort(403)
        if request.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
            abort(403)
        # Native loopback clients may omit browser headers. They still need
        # the per-process session token checked by each application's wrapper.
