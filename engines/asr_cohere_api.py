"""Cohere Transcribe Arabic through the documented V2 trial-key API."""
from engines.asr_cloud import CloudRecognizer, result
from engines.asr_cohere_local import select_language
from engines.cancellation import generation_scope
from engines.cloud_http import provider_key
from engines.provider import ProviderBinding, ProviderError
from engines.usage import LOCAL_RATE, MonthlyQuota, RollingQuota


class CohereApiRecognizer(CloudRecognizer):
    name = "cohere-api"
    languages = {"en", "ar"}
    endpoint = "https://api.cohere.com/v2/audio/transcriptions"
    model = "cohere-transcribe-arabic-07-2026"

    def transcribe(self, audio, sample_rate, *, hint_language=None, prompt=None, stop_event=None):
        with generation_scope(stop_event):
            language, duration = select_language(hint_language), len(audio) / sample_rate
            wav = self._audio(audio, sample_rate)
            if wav is None:
                return result("", language, duration, self.name)
            self.quota.take(duration)
            response = self.http.post(self.endpoint, headers={"Authorization": "Bearer " + provider_key(self.credentials, self.name)},
                data={"model": self.model, "language": language}, files={"file": ("utterance.wav", wav, "audio/wav")}, timeout=20)
            if not isinstance(response, dict) or "text" not in response:
                raise ProviderError()
            return result(response["text"], language, duration, self.name)


def build(preference, credentials):
    return ProviderBinding(CohereApiRecognizer(credentials), rate=LOCAL_RATE
                            if preference.account_kind == "trial" and preference.training_consent else None,
                            quota=MonthlyQuota(requests=1000), monthly_cap=0, windows=(RollingQuota(60, requests=5),))
