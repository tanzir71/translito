"""Azure Translator v3 standard text API, with HTML span preservation."""
from engines.cloud_http import CloudHttp, provider_key
from engines.mt_cloud import CloudText, MarkupTranslator
from engines.provider import ProviderBinding, ProviderError
from engines.usage import LOCAL_RATE, MonthlyQuota, Units


class AzureTranslator(MarkupTranslator):
    name = "azure"
    adapter = "azure"
    endpoint = "https://api.cognitive.microsofttranslator.com/translate"

    def __init__(self, credentials, *, region="", http=None):
        self.credentials, self.region = credentials, region
        self.http = http or CloudHttp()

    def request(self, text, source, target, **kwargs):
        headers = {"Ocp-Apim-Subscription-Key": provider_key(self.credentials, self.name)}
        if self.region and self.region != "global":
            headers["Ocp-Apim-Subscription-Region"] = self.region
        metering = {}
        response = self.http.post(self.endpoint, params={"api-version": "3.0", "from": source,
                                 "to": target, "textType": "html"}, headers=headers, json=[{"Text": text}], capture_headers=metering)
        try:
            count = metering.get("x-metered-usage", "")
            return CloudText(response[0]["translations"][0]["text"], Units(characters=int(count)) if count.isdigit() else None)
        except (TypeError, KeyError, IndexError):
            raise ProviderError() from None


def build(preference, credentials):
    # Only the confirmed F0 account is zero-cost. The paid S1 rate depends on
    # the user's region/agreement and is not guessed from an unconfigured key.
    return ProviderBinding(AzureTranslator(credentials, region=preference.region),
                            rate=LOCAL_RATE if preference.account_kind == "free" else None,
                            quota=MonthlyQuota(characters=2_000_000), monthly_cap=0)
