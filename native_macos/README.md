# Translito for macOS (Xcode)

Translito is a fully native Swift audio transcription and translation app. No Python or BlackHole is required for system audio.

## What it uses

| Concern | Technology |
| --- | --- |
| System/desktop audio | ScreenCaptureKit (`capturesAudio`), no virtual driver needed |
| Microphone / virtual devices (BlackHole etc.) | AVAudioEngine input tap |
| Speech recognition | WhisperKit (Core ML, on-device, models download once) |
| Translation | Apple Translation framework (on-device language packs) |
| UI | SwiftUI — main window + menu bar extra + Settings |

## Pipeline contract (matches the Windows app)

Capture at native rate (48 kHz for system audio) → downmix to mono → resample to 16 kHz Float32 (`AVAudioConverter`) → 6-second chunks → silence gate (peak < 1e-6, rms < 5e-7) → gain boost for quiet chunks (`min(200, 0.9/peak)`) → Whisper ASR → translation → transcript entries saved as `transcript_<timestamp>.txt`.

## Build

1. Open `DesktopAudioTranslator/DesktopAudioTranslator.xcodeproj` in Xcode.
2. First build: Xcode resolves the WhisperKit Swift package automatically (File → Packages → Resolve Package Versions if it doesn't).
3. Run the `DesktopAudioTranslator` scheme. It produces `Translito.app`; signing is automatic with your team, and the app is sandboxed with audio-input, network-client (model download), and user-selected-file entitlements already configured.

## Build the DMG

With Xcode installed:

```bash
./build_dmg.sh
```

To repackage an existing working native build with the current Translito branding and icon:

```bash
./build_dmg.sh --prebuilt "/path/to/DesktopAudioTranslator.app"
```

Both paths produce `Translito.dmg` and `dist/Translito.app`.

## First run

- **System Audio**: macOS prompts for **Screen Recording** permission (ScreenCaptureKit requires it even for audio-only). Grant it in System Settings → Privacy & Security, then relaunch.
- **Microphone / BlackHole**: macOS prompts for **Microphone** permission.
- **Whisper model**: downloads on first Start (default `small`, changeable in Settings), then runs fully offline.
- **Translation**: macOS may prompt once to download the language pack (e.g. Arabic→English); after that it's fully on-device.

## Performance notes

- Models preload in the background at app launch with visible progress (download %, then "Optimizing model for this Mac"). The Core ML optimization pass runs once per model (~1–2 min) and is cached; afterwards loads take seconds and Start is instant.
- Chunks are emitted early when speech is followed by a ~0.7 s pause, so you rarely wait the full chunk window. Steady background noise doesn't trigger early emission — it falls back to the fixed window.
- Faster transcription: pick a smaller Whisper model in Settings ("base" is ~3× faster than "small" and fine for clear speech; "tiny" is fastest). Shorten the chunk length for snappier turnaround.

## Speak Mode (talk in English, it speaks your target language)

Reverse pipeline: your mic → Whisper → translation → AVSpeechSynthesizer, played into a chosen **output** device. To use it in Slack/Zoom/Meet:

1. Install [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) (macOS can't create a virtual mic without a driver — BlackHole is the routing layer).
2. In the app, switch to **Speak Translation** mode, pick your real mic and "Speak to: BlackHole 2ch".
3. In Slack/Zoom, select **BlackHole 2ch as the microphone**.
4. Talk normally; participants hear the translated voice. Wear headphones to avoid your mic picking up room audio.

Settings → Speak Mode lets you pick the voice (system voices for the target language; add higher-quality ones in System Settings → Accessibility → Spoken Content) and enable monitoring through your own speakers. Everything you say is also logged to the transcript. Note: speech lags your voice by roughly one chunk length (default 6 s) plus processing time — shorten the chunk length in Settings for snappier conversation.

## Using BlackHole (optional fallback)

Only needed if you can't use System Audio mode. Route macOS output to a Multi-Output Device containing BlackHole + your speakers, then select **BlackHole 2ch** as the app's source (never the Multi-Output Device). The app detects virtual devices by name and shows a specific hint if they're silent.

## Source layout

```
DesktopAudioTranslator/
├── DesktopAudioTranslatorApp.swift   App scenes (window, menu bar, settings)
├── ContentView.swift                 Main window + hidden .translationTask host
├── Audio/
│   ├── AudioTypes.swift              AudioChunk, CaptureSource, errors
│   ├── AudioDeviceManager.swift      Core Audio input enumeration, virtual detection
│   ├── AudioChunkProcessor.swift     Mono/16k/6s chunking, silence gate, gain
│   ├── SystemAudioCapture.swift      ScreenCaptureKit system audio
│   └── InputDeviceCapture.swift      AVAudioEngine mic/virtual input
├── ML/
│   ├── TranscriptionEngine.swift     WhisperKit actor
│   └── TranslationBridge.swift       Apple Translation request queue
├── Pipeline/
│   └── TranslatorPipeline.swift      Orchestrator (capture → ASR → translate → store)
├── Support/
│   ├── AppSettings.swift             Persisted prefs (config.ini equivalent)
│   ├── Languages.swift               Language options
│   ├── TranscriptStore.swift         Human-readable transcript files
│   └── PermissionsManager.swift      Screen Recording / Microphone helpers
└── Views/
    ├── MenuBarView.swift
    └── SettingsView.swift
```

## Notes

- Transcripts default to the app container's `Documents/Transcripts`; pick any folder in Settings (persisted via security-scoped bookmark).
- Capture callbacks never run ASR/translation — chunks flow through an `AsyncStream` into a sequential processing task, so transcript ordering is stable.
- Translation fills in asynchronously per entry; if a language pack is missing you still get the source transcript plus a hint.
- If WhisperKit's API changes in a future major version, the pinned dependency (`0.9.0 ..< 1.0.0`) can be bumped in the project's Package Dependencies.
