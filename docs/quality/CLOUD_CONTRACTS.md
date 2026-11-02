# Cloud contract checks — 2026-11-02

These are implementation references, not live-account acceptance results. No
provider key, meeting text/audio or paid inference request was used to check them.
All providers remain disabled until explicit configuration and a successful Test.

| Provider | Verified contract / limits | Primary references |
|---|---|---|
| Azure standard MT | v3 `/translate`, JSON text array, `from`/`to`, HTML with `notranslate` spans, subscription key and optional regional header. F0 has 2M characters/month. The adapter supports confirmed F0; paid S1 pricing is left unconfigured rather than guessed from a region-dependent price table. | [Translate](https://learn.microsoft.com/azure/ai-services/translator/text-translation/reference/v3/translate), [authentication](https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/reference/v3/reference), [pricing](https://azure.microsoft.com/en-us/pricing/details/translator/) |
| Google Basic MT | v2 NMT JSON translation, HTML input, source/target, API key in `X-Goog-Api-Key` header. First 500k characters/month are covered by credit; subsequent NMT text is $20/M characters. The app reserves a conservative markup-inclusive input ceiling and tracks only its own requests. | [v2 API](https://docs.cloud.google.com/translate/docs/reference/rest/v2/translate), [header mapping](https://docs.cloud.google.com/apis/docs/system-parameters), [pricing](https://cloud.google.com/products/translate/pricing) |
| DeepL | API Free: 500k characters/month, `api-free.deepl.com`, key suffix `:fx`. XML exclusions, v2 tag handling, explicit EN-US/PT-PT targets, last two context pairs. `/v3/languages?resource=glossary` gates glossary creation; immutable v3 dictionaries are cached by hashed key/pair/content. Unsupported pairs keep protected spans without a server glossary. | [official SDK](https://github.com/DeepLcom/deepl-python), [translate](https://developers.deepl.com/api-reference/translate/request-translation), [v3 glossary](https://developers.deepl.com/api-reference/multilingual-glossaries/create-a-glossary), [usage](https://developers.deepl.com/docs/resources/usage-limits) |
| Cohere Arabic ASR | V2 multipart audio transcriptions: `model=cohere-transcribe-arabic-07-2026`, `language=ar` or `en`, file and bearer key; response has `text`. Trial: 5 requests/minute, 1,000 calls/month. Trial inputs/outputs may be reused for research and improvement; personal information is not intended for trial use. Requires explicit reuse consent and a confirmed trial account. | [quickstart](https://docs.cohere.com/v2/docs/audio-transcription-quickstart), [limits](https://docs.cohere.com/v2/docs/rate-limits), [privacy §2.3](https://cohere.com/privacy) |
| Groq ASR | OpenAI-compatible audio transcriptions, `whisper-large-v3`, WAV/FLAC, optional language, verbose JSON, temperature 0. Minimum billed audio is 10 seconds per request. Published free limits: 20 RPM, 2,000 RPD, 7,200 audio seconds/hour and 28,800/day; account limits may differ. | [speech API](https://console.groq.com/docs/speech-to-text), [limits](https://console.groq.com/docs/rate-limits) |
| Gemini MT | Stable `gemini-3.1-flash-lite`; free-tier data may improve products, requiring separate opt-in. REST `generationConfig.responseFormat.text` uses `mimeType=APPLICATION_JSON` and a translations-array schema. Batches 1–5 sentences already available in a row, never waits for future speech. Two context pairs and glossary are prompt data; one retry verifies every protected span. Paid pricing is not configured. | [pricing](https://ai.google.dev/gemini-api/docs/pricing), [structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en), [API reference](https://ai.google.dev/api/generate-content) |

The transport uses the already-installed HTTPX2 2.16.0 runtime, verified against
its local signatures. It keeps certificate verification on, recognizes native
Windows roots, bounds timeouts, refuses redirects, and converts HTTP/JSON errors
to static messages. Keys are never URL query parameters. Contract tests use
HTTPX2 MockTransport, including error bodies containing fake key/text sentinels.
See [HTTPX2](https://github.com/pydantic/httpx2).

These six contracts are registered, off by default, and covered by fake HTTP
request tests. Test/usage cards, shared pair LID, Advanced one-way routing,
restart-safe rolling quotas and local token buckets are implemented. Azure's
published `X-metered-usage`, DeepL billed characters, known Google input length
and Gemini token metadata settle conservative reservations without removing the
original records. Unknown outcomes retain their reservations. Limits describe
Translito's own ledger; account usage outside the app is not visible to it.

No production booster is selected without a measured bake-off. No live-cloud
quality, latency or billing acceptance has been established by these tests.
