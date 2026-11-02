"""Verified TLS, bounded requests and static errors at the cloud boundary."""
import os

from engines.cancellation import check_cancelled
from engines.provider import AuthenticationError, ProviderError, ProviderNetworkError, ProviderQuotaError


class CloudHttp:
    def __init__(self, client=None):
        self.client = client

    def post(self, url, **kwargs):
        check_cancelled()
        if os.environ.get("OFFLINE_ONLY", "0").strip() == "1":
            raise ProviderNetworkError()
        import httpx2 as httpx
        if self.client is None:
            from native_tls import configure_native_tls
            configure_native_tls()
            self.client = httpx.Client(timeout=httpx.Timeout(10, connect=4), follow_redirects=False)
        try:
            kwargs["follow_redirects"] = False
            response = self.client.post(url, **kwargs)
        except (httpx.HTTPError, OSError):
            raise ProviderNetworkError() from None
        check_cancelled()
        if response.status_code in {401, 403}:
            raise AuthenticationError()
        if response.status_code in {429, 456}:
            raise ProviderQuotaError()
        if response.status_code >= 500:
            raise ProviderNetworkError()
        if response.status_code < 200 or response.status_code >= 300 or len(response.content) > 2 * 1024 * 1024:
            # In particular, never forward credentials through an HTTP redirect.
            raise ProviderError()
        try:
            return response.json()
        except (ValueError, UnicodeError):
            raise ProviderError() from None


def provider_key(credentials, provider):
    try:
        value = credentials.get(provider)
    except Exception:
        raise AuthenticationError() from None
    if not isinstance(value, str) or not value.strip() or "\r" in value or "\n" in value:
        raise AuthenticationError()
    return value.strip()
