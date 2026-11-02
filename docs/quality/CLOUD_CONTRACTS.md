# Cloud contract checks — 2026-11-02

These are implementation references, not live-account acceptance results. No
provider key, meeting text/audio or paid inference request was used to check them.
All providers remain disabled until explicit configuration and a successful Test.

| Provider | Verified contract / limits | Primary references |
|---|---|---|
| Azure standard MT | v3 `/translate`, JSON text array, `from`/`to`, HTML with `notranslate` spans, subscription key and optional regional header. F0 has 2M characters/month. The adapter supports confirmed F0; paid S1 pricing is left unconfigured rather than guessed from a region-dependent price table. | [Translate](https://learn.microsoft.com/azure/ai-services/translator/text-translation/reference/v3/translate), [authentication](https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/reference/v3/reference), [pricing](https://azure.microsoft.com/en-us/pricing/details/translator/) |
| Google Basic MT | v2 NMT JSON translation, HTML input, source/target, API key in `X-Goog-Api-Key` header. First 500k characters/month are covered by credit; subsequent NMT text is $20/M characters. The app reserves a conservative markup-inclusive input ceiling and tracks only its own requests. | [v2 API](https://docs.cloud.google.com/translate/docs/reference/rest/v2/translate), [header mapping](https://docs.cloud.google.com/apis/docs/system-parameters), [pricing](https://cloud.google.com/products/translate/pricing) |
| DeepL | JSON `text` array, source/target codes, `DeepL-Auth-Key` authorization, XML `ignore_tags`, optional glossary ID and non-billed context. Tag handling v2 is documented. API Free monthly quota and supported glossary pairs still need a final account/contract check before registration. | [translate](https://developers.deepl.com/api-reference/translate/request-translation), [usage](https://developers.deepl.com/docs/resources/usage-limits) |
| Cohere Arabic ASR | V2 multipart audio transcriptions: `model=cohere-transcribe-arabic-07-2026`, required `language=ar` or `en`, file and bearer key; response has `text`. Trial: 5 requests/minute, 1,000 calls/month. | [quickstart](https://docs.cohere.com/v2/docs/audio-transcription-quickstart), [Arabic release](https://docs.cohere.com/changelog/transcribe-arabic), [limits](https://docs.cohere.com/v2/docs/rate-limits) |
| Groq ASR | OpenAI-compatible audio transcriptions, `whisper-large-v3`, WAV/FLAC, optional language, verbose JSON, temperature 0. Minimum billed audio is 10 seconds per request. Published free limits: 20 RPM, 2,000 RPD, 7,200 audio seconds/hour and 28,800/day; account limits may differ. | [speech API](https://console.groq.com/docs/speech-to-text), [limits](https://console.groq.com/docs/rate-limits) |
| Gemini MT | `gemini-3.1-flash-lite` is a documented stable option. Free-tier inputs may be used to improve products, requiring separate opt-in. Paid text input/output is $0.25/$1.50 per million tokens. The current REST schema uses `generationConfig.responseFormat.text` with `mimeType=APPLICATION_JSON` and `schema`; response schema compatibility must be covered by request tests. | [pricing](https://ai.google.dev/gemini-api/docs/pricing), [structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en), [API reference](https://ai.google.dev/api/generate-content) |

The transport uses the already-installed HTTPX2 2.16.0 runtime, verified against
its local signatures. It keeps certificate verification on, recognizes native
Windows roots, bounds timeouts, refuses redirects, and converts HTTP/JSON errors
to static messages. Keys are never URL query parameters. Contract tests use
HTTPX2 MockTransport, including error bodies containing fake key/text sentinels.
See [HTTPX2](https://github.com/pydantic/httpx2).

Remaining integration work: DeepL/Gemini/Groq/Cohere adapters and request tests;
shared pair-LID/postprocessing around cloud ASR; prefer ready/fast local Cohere
before cloud in Free, with cloud before the weak stock-Whisper fallback;
provider Test/usage/privacy cards; free quota windows; cloud routing in Advanced
one-way mode. No production booster is selected without a measured bake-off.
