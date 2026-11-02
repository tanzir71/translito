"""Cloud Translation Basic v2 NMT, with keys in headers rather than URLs."""
from decimal import Decimal

from engines.cloud_http import CloudHttp, provider_key
from engines.mt_cloud import CloudText, MarkupTranslator
from engines.provider import ProviderBinding, ProviderError
from engines.usage import Allowance, Rate, Units


class GoogleTranslator(MarkupTranslator):
    name = "google"
    adapter = "google"
    endpoint = "https://translation.googleapis.com/language/translate/v2"

    def __init__(self, credentials, *, http=None):
        self.credentials = credentials
        self.http = http or CloudHttp()

    def request(self, text, source, target, **kwargs):
        response = self.http.post(self.endpoint, headers={"X-Goog-Api-Key": provider_key(self.credentials, self.name)},
                                  json={"q": [text], "source": source, "target": target, "format": "html", "model": "nmt"})
        try:
            return CloudText(response["data"]["translations"][0]["translatedText"], Units(characters=len(text)))
        except (TypeError, KeyError, IndexError):
            raise ProviderError() from None


def build(preference, credentials):
    confirmed = preference.account_kind in {"free", "paid"}
    return ProviderBinding(GoogleTranslator(credentials),
                            rate=Rate(per_million_chars=Decimal("20")) if confirmed else None,
                            allowance=Allowance(characters=500_000), monthly_cap=0)
