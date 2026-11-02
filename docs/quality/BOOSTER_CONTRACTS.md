# Booster evaluation contracts — 2026-11-02

The desktop does not register these paid candidates. The thin wire contracts
live in `tools/eval/streaming_protocols.py`; the opt-in transport/accounting runner
is integrated into the P0 CLI. See [PAID_EVALUATION.md](PAID_EVALUATION.md) for its
zero-default allocation, account-verified session ceilings and measurement limits.
Synthetic contract/socket tests are not recorded vendor sessions or quality
measurements. Approved accounts/spending and a measured comparison are still
required before selecting a production booster. No paid call has been made.
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

## Gemini Live Translate preview worker

`engines/interp_gemini_live.py` uses pinned `google-genai==2.33.0`, the official
LiveConnectConfig/TranslationConfig types, one-way output and
`echo_target_language=False`. Its dedicated asyncio thread accepts 100 ms
16kHz PCM frames and emits source/target text and 24kHz audio. A tested free-tier
key, separate data-reuse consent and $0 paid cap are required before a client
or ledger is opened. It never selects paid Vertex/ADC credentials.

Session resumption handles stay in memory. GoAway reconnects, Stop cancels a
blocked receiver, and repeated failures produce a static Free-fallback event.
Preview capability rejection retries once without resumption. Uncertain uploads
retain conservative usage reservations; confirmed uploads settle in 30-second
blocks. The transport never logs SDK exception details; WebSocket debug wire
logging is disabled because it includes authentication and private content.

The installed SDK was exercised through a fake WebSocket with sockets blocked:
header-only authentication, setup serialization, transcription decoding and
PCM upload passed. This is transport evidence, not a vendor session.

The desktop now exposes an opt-in Live interpreter profile and a separate Live
provider card. Its public-clip Test must succeed before enablement; the free
account and reuse choices start unchecked. Free/Offline/Custom do not open the
live client. Advanced one-way mode keeps the Free path. Capture resamples 48kHz
loopback to 100ms 16kHz frames; the existing VAD still retains chunks for recovery.
Source/target events update the existing transcript row, and already-target
speech remains source-only unless both-language captions were requested.

Original-voice Speak policy uses the existing cheap pair-LID pass on buffered
VAD speech. Same-audience speech is passed through, muted or read with the
selected voice according to the setting; it does not run full ASR a second time.
Generated target PCM uses the persistent player. Recognized glossary aliases
are restored in source text. Lines with protected English terms hold native
audio until verification; a changed term uses the shared Free translator and
local voice. Later target text is retained after the first idle deadline, and
missing translations trigger Free recovery instead of vanishing.

Completed source offsets retire confirmed audio. When timestamps are absent,
unconfirmed VAD chunks stay in memory until Stop or recovery, preserving speech
at the cost of possible overlap and additional memory. Free recovery warns
that overlapping text may repeat. Reconnect clears queued old output; Stop
keeps queued text while suppressing playback. Saved entries add mode/engine.
These policies have synthetic desktop-flow tests, not live-model acceptance.
The physical 30-minute Speak test, real transcript/audio timing, rapid switching
behavior and free-account availability remain unverified. Optional dubbed
Listen output has not been added.

Windows preview inspection confirmed the separate profile choice and Live card,
unchecked free-account/reuse/enable controls, masked key field, public-clip
description and $0 paid cap. The preview Test action reported no key access,
requests or settings writes. The real profile stayed on Free; its config length
and timestamp were unchanged and no real usage file was created. Stop releases
retained audio and queued PCM while preserving transcript text.

SpeechOutputPlayer now has persistent PCM playback, per-route resampling with
retained boundaries, and stream-generation cancellation on reconnect. Recovery
keeps the replacement device open. Synthetic tests check 44.1/48kHz alignment,
irregular chunks, failed-route replacement, old queued audio and late callbacks
after Stop. Hardware output and meeting-app routing remain unverified.

Primary references: [Live translation](https://ai.google.dev/gemini-api/docs/live-api/live-translate),
[session management](https://ai.google.dev/gemini-api/docs/live-api/session-management),
[free/paid pricing](https://ai.google.dev/gemini-api/docs/pricing),
[SDK release](https://github.com/googleapis/python-genai/releases/tag/v2.33.0).
