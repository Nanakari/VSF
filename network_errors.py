"""Remove credentials echoed by upstream error responses."""
from urllib.parse import quote, quote_plus


def redact_secret(value: object, secret: str) -> str:
    text = str(value)
    if secret:
        for variant in {secret, quote(secret, safe=""), quote_plus(secret)}:
            text = text.replace(variant, "[REDACTED]")
    return text
