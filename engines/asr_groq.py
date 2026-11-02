"""Groq Whisper transcription with verbose scores and local quota protection."""
from engines.asr_cloud import CloudRecognizer, number, result
from engines.cancellation import generation_scope
from engines.cloud_http import provider_key
from engines.provider import ProviderBinding, ProviderError
from engines.usage import Rate, RollingQuota


class GroqRecognizer(CloudRecognizer):
    name = "groq"
    endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"
    model = "whisper-large-v3"

    def transcribe(self, audio, sample_rate, *, hint_language=None, prompt=None, stop_event=None):
        with generation_scope(stop_event):
            duration = len(audio) / sample_rate
            wav = self._audio(audio, sample_rate)
            if wav is None:
                return result("", hint_language or "ar", duration, self.name)
            self.quota.take(duration)
            data = {"model": self.model, "response_format": "verbose_json", "temperature": "0"}
            if hint_language:
                data["language"] = hint_language
            if prompt:
                # A UTF-8 byte ceiling is conservative for Whisper's 224-token
                # prompt limit and never splits a Unicode character.
                data["prompt"] = prompt.encode("utf-8")[:220].decode("utf-8", errors="ignore")
            response = self.http.post(self.endpoint, headers={"Authorization": "Bearer " + provider_key(self.credentials, self.name)},
                                      data=data, files={"file": ("utterance.wav", wav, "audio/wav")}, timeout=20)
            if not isinstance(response, dict) or not isinstance(response.get("text"), str):
                raise ProviderError()
            text, scores, silence = response["text"], [], []
            segments = response.get("segments")
            if isinstance(segments, list) and segments:
                accepted = []
                for segment in segments:
                    if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                        raise ProviderError()
                    score, no_speech, compression = (number(segment.get(key)) for key in
                                                    ("avg_logprob", "no_speech_prob", "compression_ratio"))
                    if compression is not None and compression > 2.4 or (
                            score is not None and score < -1 and no_speech is not None and no_speech > .6):
                        continue
                    accepted.append(segment["text"])
                    if score is not None:
                        scores.append(score)
                    if no_speech is not None:
                        silence.append(no_speech)
                text = " ".join(accepted)
            return result(text, hint_language or response.get("language") or "ar", duration, self.name,
                           avg_logprob=sum(scores) / len(scores) if scores else None,
                           no_speech_prob=max(silence) if silence else None)


def build(preference, credentials):
    return ProviderBinding(GroqRecognizer(credentials), rate=Rate(minimum_audio_seconds=10)
                            if preference.account_kind == "free" else None, monthly_cap=0,
                            windows=(RollingQuota(60, requests=20), RollingQuota(3600, audio_seconds=7200),
                                     RollingQuota(86400, requests=2000, audio_seconds=28800)))
