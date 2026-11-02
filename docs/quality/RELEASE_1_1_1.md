# Windows 1.1.1 release validation

The patch preserves the selected Fast/Balanced/Best decoder beam size when the
bilingual recognizer loads a prepared Arabic code-switch fallback. Previously,
both missing Cohere weights and a runtime Cohere failure could silently reset
the replacement recognizer to Balanced. Model choices and fallback order are
unchanged. No model weights or provider credentials are bundled.

Validation before packaging: **351 tests passed**, including six cases checking
the real Whisper adapter's decoder arguments after both kinds of fallback.
The existing Torch JIT deprecation warning remains. Installer VERSION, Inno and
EXE resource versions agree on 1.1.1. Release assets and installation validation
are pending; download pages will change only after asset verification.

The cache-only bilingual switching report in LOCAL_HARDWARE.md independently
verifies EN → AR → EN rows and English no-MT behavior using synthetic English
and public MSA. It does not establish Saudi accuracy, gated Cohere performance
or the four-second latency target. Physical VB-CABLE routing and real provider
accounts remain unverified. The owner approved driver installation/test, but
Windows rejected the launch before a driver process started; the separate
manual Windows installation step remains pending. This app patch does not
change Windows settings or address that driver-launch failure.
