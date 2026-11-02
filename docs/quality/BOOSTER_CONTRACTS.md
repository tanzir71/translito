# Booster evaluation contracts — 2026-11-02

The desktop does not register these paid candidates. The thin wire contracts
live in `tools/eval/streaming_protocols.py` and make no network calls. Nine
synthetic contract tests pass; they are not recorded vendor sessions or quality
measurements. A transport/accounting runner, approved accounts/spending and a
measured comparison are still required before selecting a production booster.
The owner waived the private Saudi evaluation set, so its acceptance criteria
remain unverified.

| Candidate | Verified wire contract | Cost caveat |
|---|---|---|
| Soniox | `stt-rt-v5`; header bearer authentication, 16kHz mono PCM16, strict English/Arabic hints, original/translation tokens, endpoint markers and one-way/two-way config. Empty **text** frame ends the session. | Current realtime token prices are $2/M audio tokens and $4/M input/output text tokens. The advertised roughly $0.12/audio-hour is an estimate; translated output also adds text tokens. Do not treat it as a fixed hourly ceiling. |
| Speechmatics | Enhanced uses `language=ar_en`; Melia 1 uses `language=multi` with English/Arabic hints. Wait for RecognitionStarted before binary audio; EndOfStream includes the number of audio frames. Melia rejects Enhanced's server endpoint config. | Current realtime page lists Enhanced $0.40/hour and Melia 1 $0.20/hour before an optional training discount. The discount stays off. Signup credit is account-specific and must not be assumed without checking its balance/expiry. |
| ElevenLabs | `scribe_v2_realtime`, key in header, PCM16 base64 chunks, VAD commits, Arabic/English secondary languages. Delayed timestamp events must not duplicate committed text. | Base API price is $0.39/hour. Realtime reference says keyterms add 20%; pricing FAQ lists a different keyterm surcharge. Keyterms require a separate explicit premium flag; the account price needs confirmation before paid evaluation. |

References checked for the contracts:

- Soniox [WebSocket](https://docs.soniox.com/api-reference/stt/websocket-api),
  [translation](https://docs.soniox.com/translation/stt-translation/rt-translation),
  [endpointing](https://docs.soniox.com/stt/rt/endpoint-detection),
  [pricing](https://soniox.com/pricing).
- Speechmatics [WebSocket](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket),
  [language packs](https://docs.speechmatics.com/speech-to-text/languages),
  [pricing](https://www.speechmatics.com/pricing).
- ElevenLabs [Realtime](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime),
  [pricing](https://elevenlabs.io/pricing/api).

The handoff's production bake-off gate remains: a clear gain over Free (for
example, at least five mixed-segment WER points or three chrF), English-term
recall and latency measured on the same inputs. No candidate is recommended on
the strength of these schema tests.
