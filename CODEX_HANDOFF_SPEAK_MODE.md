# Codex Handoff: Windows Feature Parity (Speak Mode + Everything Since)

Date: 2026-07-02 (updated same day with all features shipped in the native macOS app)

## Goal

Bring the working Windows app (root `main.py` + `gui.py`) to feature parity with the native macOS app (`native_macos/`). The macOS app is the behavior reference for everything in this document. Features, in build order:

1. Speak Mode (mic → ASR → MT → TTS → virtual mic for Slack/Zoom)
2. Model loading progress display + preload at launch
3. Pause-based early chunk emission (latency cut)
4. Mic ambient-noise gate + Whisper anti-hallucination thresholds
5. Output-device rebinding on audio route changes
6. Noise gate sensitivity setting (slider)
7. Open at login
8. Automatic audio-device list refresh
9. Configurable global hotkeys (toggle/start/stop)
10. Installer (Windows counterpart of the macOS DMG)

macOS reference files (paths under `native_macos/DesktopAudioTranslator/DesktopAudioTranslator/`):

- `Pipeline/TranslatorPipeline.swift` — modes, status states, hotkey entry points, saved-device resolution
- `Audio/AudioChunkProcessor.swift` — chunking contract, silence + noise gates, early emission
- `ML/TranscriptionEngine.swift` — Whisper decode options and load phases
- `ML/SpeechOutputService.swift` — TTS routed to a specific output device, rebinding
- `Support/Hotkeys.swift`, `Support/AppSettings.swift`, `Views/SettingsView.swift` — hotkeys and settings UI
- `Audio/AudioDeviceObserver.swift` — device hot-plug refresh

## Read These First

- `main.py`: existing capture → Whisper → Helsinki-NLP pipeline (reuse it; everything below extends it).
- `gui.py`: device/language/model selection and start/stop flow.
- `requirements.txt`: current dependency set.
- `native_macos/README.md`: user-facing behavior documentation, including the Performance notes and Speak Mode routing.

---

## 1. Speak Mode

The user speaks into their microphone in one language (default English), the app transcribes → translates → synthesizes speech in the target language, and plays that speech into a **virtual audio device** so conferencing apps (Slack, Zoom, Teams, Meet) can select it as their microphone.

### Architecture

```
Microphone (existing soundcard capture, 16 kHz path)
  → existing chunking / silence gate / gain (unchanged)
  → Whisper ASR (source language = speak_source, default "en")
  → translation (existing Helsinki-NLP, e.g. opus-mt-en-ar)
  → NEW: TTS synthesis in target language
  → NEW: playback to a selected OUTPUT device (VB-Cable input)
  → user selects "CABLE Output (VB-Audio Virtual Cable)" as mic in Slack/Zoom
```

Speak Mode reuses the whole existing pipeline; the only new components are the TTS engine, the output-device player, and mode plumbing in the GUI. Do not fork the ASR/translation code.

### Virtual device routing on Windows

Use **VB-Audio Virtual Cable** (donationware — do NOT bundle; link to https://vb-audio.com/Cable/ and detect at runtime):

- App plays TTS to the **playback** device `CABLE Input (VB-Audio Virtual Cable)`.
- Conferencing apps use the **recording** device `CABLE Output (VB-Audio Virtual Cable)` as mic.
- Detect by name substring `"cable input"` / `"vb-audio"` (case-insensitive), plus the existing virtual keywords (`virtual`, `voicemeeter`, `blackhole`).

UI rules (mirror macOS `ContentView.speakRoutingBanner`):

- Output picker listing playback devices, virtual ones labeled "(virtual)"; real-mic picker excluding virtual devices.
- Virtual output selected → green hint: 'In Slack/Zoom, set the microphone to "CABLE Output (VB-Audio Virtual Cable)". Use headphones.'
- No virtual playback device → yellow hint with VB-Cable install link; feature still works to speakers.
- Never tell the user to select `CABLE Input` as the conferencing mic.
- Guard against selecting the same physical device as both input and output.

### TTS engine

Priority: 1) **Piper TTS** (offline, per-language voices, cache under `tts_models/`), 2) pyttsx3/SAPI5 fallback, 3) never default to cloud TTS. Abstract behind:

```python
class SpeechSynthesizer:
    def synthesize(self, text: str, language: str) -> tuple[np.ndarray, int]: ...
```

### Playback

`sounddevice` OutputStream bound to the selected device, fed from a queue on a worker thread. Serialize utterances, never overlap clips, resample TTS output to the stream rate, never block the ASR thread. Optional "monitor" toggle mirrors audio to the default speakers.

### Pipeline/GUI integration

- Mode flag `mode="listen"|"speak"`; config.ini keys: `speak_source` (en), `speak_target` (ar), `speak_mic_name`, `speak_output_device_name`, `speak_voice`, `monitor_spoken_audio`, plus `last_mode` (see hotkeys).
- Speak mode awaits translation inline (speech needs the text), then enqueues TTS; transcript entry recorded either way. Add a `Speaking…` status.
- GUI: mode toggle ("Translate Audio" / "Speak Translation"), mic + output pickers, separate language pickers per mode, routing banner, voice picker (Piper voices for target language + "Automatic").
- Echo: recommend headphones in the UI; optionally drop mic chunks captured while TTS is playing.

---

## 2. Model loading progress + preload at launch

macOS reference: `TranscriptionEngine.load(model:onProgress:)`, `TranslatorPipeline.loadModels/preloadModels`, status row in `ContentView`.

- Replace the bare "Loading models…" text with phase-aware progress:
  - **Downloading** — show percent. With `huggingface_hub`/transformers, pass a progress callback (or subclass `tqdm`) from `snapshot_download`; report `fraction = downloaded/total` per file and aggregate.
  - **Preparing/warming** — after download, while the model loads to device (CUDA/CPU) show an indeterminate spinner with text like "Preparing whisper-small… first run is slower, cached afterwards".
- **Preload at launch**: kick off model loading on a background thread as soon as the GUI opens, so Start is instant. Guard with the same lock the Start path uses; Start called mid-preload must wait, not double-load.
- GUI: progress bar + phase text in the status row (see macOS status bar: linear bar while a fraction is known, spinner otherwise).

## 3. Pause-based early chunk emission (latency)

macOS reference: `AudioChunkProcessor.earlyChunkAfterPause()` — copy the exact parameters:

- Constants: `min_speech = 1.5 s`, `tail = 0.7 s`, `body_peak_floor = 0.005`, `drop_ratio = 2.5`.
- After appending capture samples to the pending buffer (and after normal full-window extraction), if no full chunk was produced and `len(pending) >= min_speech + tail`:
  - body = pending[:-tail], tail = pending[-tail:]
  - if `peak(body) > body_peak_floor` and `rms(body) / max(rms(tail), eps) > drop_ratio` → emit the whole pending buffer as a chunk immediately and clear it.
- Steady ambient noise never triggers this (body ≈ tail RMS), so it falls back to the fixed window. Keep the 6 s default window as the cap.
- This is the single biggest perceived-latency win; implement it inside the existing chunk accumulation loop in `capture_audio`/`process_audio`.

## 4. Mic noise gate + Whisper anti-hallucination thresholds

Problem this fixes: mic background noise (car horns, room tone) passed the old silence gate (tuned for loopback digital silence), then the auto-gain (`min(200, 0.9/peak)`) amplified it into audio Whisper hallucinates words from.

macOS reference: `AudioChunkProcessor` noise gate + `TranscriptionEngine` decode options.

- **RMS noise gate**, applied per chunk BEFORE the gain boost, only for real microphones (never for loopback/virtual devices — quiet desktop audio is real content):
  - default threshold `0.002` RMS (Float32 normalized samples), `0` = off.
  - gated chunks count toward the silence-run counter but don't show the "no audio" hint unless digitally silent.
- **Whisper thresholds** (transformers `generate` kwargs / faster-whisper equivalents):
  - `logprob_threshold = -1.0`, `no_speech_threshold = 0.6`, `compression_ratio_threshold = 2.4`.
  - With transformers pipeline, pass via `generate_kwargs`; segments judged no-speech return empty instead of junk.

## 5. Output-device rebinding on route changes

macOS bug this fixed: Bluetooth headset mics (HFP) trigger an audio-route reconfiguration that silently reset the TTS output binding, so speech played to the headphones instead of the virtual device.

Windows equivalent: WASAPI streams die or the device list shifts when a BT headset switches profiles or the default device changes.

- Never cache device indices across route changes — resolve the output device **by name** and (re)open the `sounddevice.OutputStream` at playback time if the stream is closed/invalid.
- Wrap stream writes in try/except (`PortAudioError`); on failure, re-resolve the device by name, reopen, retry once.
- Advise in the UI that Bluetooth headset mics drop call audio to low-quality HFP; recommend built-in/wired mic + headphones for listening only.

## 6. Noise gate sensitivity setting

macOS reference: Settings → Capture → "Mic noise gate" slider.

- Slider range 0 … 0.008 RMS, default 0.002; label buckets: 0 = "Off", <0.0015 = "Low", <0.003 = "Medium", else "High".
- Persist as `mic_noise_gate` in config.ini. 0 must be a valid stored value (don't confuse "unset" with "off").
- Help text: raise in noisy rooms, lower if soft speech gets clipped; never applies to loopback/virtual sources.

## 7. Open at login

macOS reference: Settings → General → "Open at login" (SMAppService).

- Windows: toggle writes/removes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value `DesktopAudioTranslator` pointing at the installed exe (or a Startup-folder shortcut if preferred).
- Reflect actual state on settings open (read the registry, don't trust a cached bool). Show errors inline and revert the toggle on failure.

## 8. Automatic device-list refresh

macOS reference: `AudioDeviceObserver` (Core Audio property listener → notification → pickers refresh).

- Windows: listen for `WM_DEVICECHANGE` in the GUI message loop (or poll `sounddevice.query_devices()` every ~3 s as a fallback; call `sounddevice._terminate()/_initialize()` to force PortAudio to rescan).
- On change: refresh mic/output pickers, keep current selections when still present, fall back sensibly (first real mic; first virtual output) when not.
- Keep the manual refresh button as well.

## 9. Configurable global hotkeys

macOS reference: `Support/Hotkeys.swift` + `TranslatorPipeline` hotkey entry points + Settings → Hotkeys recorders.

Defaults (use Ctrl+Alt on Windows where macOS uses ⌃⌥):

| Action | Default | Behavior |
| --- | --- | --- |
| Toggle Listen / Speak | Ctrl+Alt+T | Idle → start `last_mode` automatically; running in listen → switch to speak; running in speak → switch to listen |
| Start Listening | Ctrl+Alt+L | Starts (or switches to) listen mode with the saved source |
| Start Speaking | Ctrl+Alt+S | Starts (or switches to) speak mode with saved mic + virtual output |
| Stop | Ctrl+Alt+X | Stops capture and saves the transcript |

- Implementation: `RegisterHotKey` via the `keyboard` package (simplest; needs no elevation for normal use) or `global-hotkeys`/`pynput`. Hotkeys must fire while other apps (Slack/Zoom) are focused.
- "Saved devices" resolution (mirror `savedListenSource`/`savedSpeakDevices`): listen → last selected source from config (fallback: desktop loopback); speak → `speak_mic_name` (fallback: first real mic) + `speak_output_device_name` (fallback: first virtual playback device). Resolve by name at press time, not cached indices.
- Persist `last_mode` ("listen"/"speak") on every successful start.
- Settings UI: a recorder row per action (capture the next key combo pressed, show it, allow clear/reset). Persist as strings in config.ini (e.g. `hotkey_toggle = ctrl+alt+t`).
- Switching modes via hotkey = clean stop (transcript saved) then start; reuse the normal start/stop code paths.

## 10. Installer (DMG counterpart)

macOS shipped as a DMG (drag-to-Applications). Windows equivalent:

- Bundle with **PyInstaller** (`--windowed`, one-dir mode is safer than one-file for model caches and startup time).
- Wrap with **Inno Setup** (installer exe, Start Menu shortcut, optional "run at startup" checkbox wired to the same registry mechanism as §7).
- Exclude models from the bundle — they download on first run with the §2 progress UI.
- Do NOT bundle VB-Cable (license); the installer may show a post-install page linking to it.
- Note in docs: unsigned installers trip SmartScreen; users click "More info → Run anyway", or sign with a code-signing cert later.

---

## Status states (parity checklist)

Ready, Loading models (with download %/phase text), Listening, Transcribing, Translating, Speaking, No audio (with device-specific hint), Permission needed (Windows: mic privacy settings), Error.

## Acceptance criteria (new features; Speak Mode criteria unchanged)

- Model download shows live percent; "preparing" phase distinguishable; models preload at launch and Start is instant afterwards.
- Speaking a sentence and pausing yields a transcript entry within ~1 s of the pause (plus ASR/MT time) rather than the full 6 s window; constant room noise still emits on the fixed window (i.e., never early).
- Car honk / keyboard clatter with the gate at Medium produces no transcript entries; whispering with the gate at Low still transcribes.
- Pulling a Bluetooth headset mid-session doesn't silence TTS: playback recovers to the configured virtual device.
- Changing the gate slider takes effect on the next start; Off transcribes everything.
- Login toggle survives app restart and matches the registry state.
- Plugging/unplugging a USB mic updates the pickers within a few seconds without restart.
- Every hotkey works while Slack is the focused app; toggle from idle starts `last_mode`; all hotkeys re-recordable and persisted.
- Installer produces a Start-Menu app that runs on a clean Windows 11 VM without Python installed.

## Pitfalls (new ones — Speak Mode pitfalls unchanged)

- Do not run the noise gate on loopback/virtual sources — it will drop quiet desktop audio.
- Gate check must happen BEFORE the auto-gain, on raw chunk RMS.
- Early-emit thresholds are relative (body vs tail RMS), not absolute — absolute thresholds break on hot/cold mics.
- Don't cache PortAudio device indices anywhere; always re-resolve by name.
- `keyboard` global hooks can require admin in elevated apps' focus; document this, don't silently fail.
- PyInstaller one-file mode + transformers = painful startup and temp-dir extraction; use one-dir.

## References

- macOS implementation in this repo: `native_macos/DesktopAudioTranslator/`
- VB-Audio Virtual Cable: https://vb-audio.com/Cable/
- Piper TTS: https://github.com/rhasspy/piper (voices: https://huggingface.co/rhasspy/piper-voices)
- sounddevice docs: https://python-sounddevice.readthedocs.io/
- keyboard (global hotkeys): https://github.com/boppreh/keyboard
- Inno Setup: https://jrsoftware.org/isinfo.php
