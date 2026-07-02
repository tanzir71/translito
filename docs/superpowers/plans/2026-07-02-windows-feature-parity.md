# Windows Feature Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the root Windows Python app to parity with the native macOS app for Speak Mode and the follow-up quality-of-life features in `CODEX_HANDOFF_SPEAK_MODE.md`.

**Architecture:** Keep `main.py` as the runtime pipeline and `gui.py` as the Tk shell, but split reusable behavior into small modules: config persistence, audio chunk processing, device discovery, TTS/playback, login, hotkeys, and model loading. Tests cover the hardware-independent behavior first; GUI and audio hardware paths are wired through those modules.

**Tech Stack:** Python, Tkinter, soundcard, sounddevice, transformers, huggingface-hub, keyboard, optional Piper/pyttsx3/SAPI TTS, PyInstaller, Inno Setup.

---

### Task 1: Portable Parity Tests

**Files:**
- Create: `tests/test_audio_processing.py`
- Create: `tests/test_config_and_devices.py`
- Create: `tests/test_speech_output.py`

- [ ] **Step 1: Write failing tests**

Add tests for pause-based early chunk emission, steady-noise fallback, mic noise gate before gain, zero gate persistence, virtual device detection, VB-Cable routing hints, default hotkeys, and playback resampling.

- [ ] **Step 2: Run tests to verify red**

Run: `python -m pytest tests/test_audio_processing.py tests/test_config_and_devices.py tests/test_speech_output.py -q`

Expected: FAIL because the new support modules do not exist yet.

### Task 2: Core Support Modules

**Files:**
- Create: `audio_processing.py`
- Create: `app_config.py`
- Create: `device_utils.py`
- Create: `speech_output.py`
- Create: `login.py`
- Create: `hotkeys.py`
- Create: `model_loading.py`

- [ ] **Step 1: Implement minimal code for tests**

Implement the exact constants from the handoff, persistent config helpers, virtual device naming, output-device name rebinding, local TTS fallbacks, registry startup helpers, keyboard hotkey manager, and preload-safe model cache.

- [ ] **Step 2: Run tests to verify green**

Run: `python -m pytest tests/test_audio_processing.py tests/test_config_and_devices.py tests/test_speech_output.py -q`

Expected: PASS.

### Task 3: Runtime Pipeline Integration

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Use the audio processor in capture**

Capture in short blocks, emit early after pauses, flush trailing audio on stop, apply the mic-only noise gate before gain, and preserve the existing transcript behavior.

- [ ] **Step 2: Add Speak Mode runtime**

Add `mode="listen"|"speak"`, speak language/device settings, inline translation before speech, `Speaking` status, and TTS queue playback to the selected output device.

- [ ] **Step 3: Add preload-aware model loading**

Load through `ModelLoadManager` so GUI preload and Start share one lock and Start waits instead of double-loading.

- [ ] **Step 4: Verify syntax**

Run: `python -m py_compile main.py audio_processing.py app_config.py device_utils.py speech_output.py login.py hotkeys.py model_loading.py`

Expected: exit 0.

### Task 4: GUI Parity

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add mode-specific controls**

Add Translate Audio / Speak Translation mode toggle, listen source picker, Speak Mode mic/output pickers, language selectors, voice selector, routing banner, monitor toggle, model progress row, mic noise gate slider, open-at-login toggle, and hotkey recorder rows.

- [ ] **Step 2: Add device refresh and hotkey behavior**

Poll device lists every 3 seconds with PortAudio rescan, preserve selections by name, and wire Ctrl+Alt defaults plus recorded combos to normal start/stop/switch paths.

- [ ] **Step 3: Add launch preload**

Start model preload after the GUI opens and display download/preparing progress in the status row.

- [ ] **Step 4: Verify syntax**

Run: `python -m py_compile gui.py`

Expected: exit 0.

### Task 5: Installer and Docs

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`
- Create: `installer/DesktopAudioTranslator.spec`
- Create: `installer/DesktopAudioTranslator.iss`
- Create: `installer/README.md`

- [ ] **Step 1: Add dependencies and packaging assets**

Add `sounddevice`, `pyttsx3`, `pyinstaller`, and installer scripts for one-dir PyInstaller plus Inno Setup. Do not bundle VB-Cable or models.

- [ ] **Step 2: Document Windows parity**

Update usage, Speak Mode routing, model preload/progress, noise gate, hotkeys, open-at-login, device refresh, and installer notes.

- [ ] **Step 3: Run final verification**

Run: `python -m pytest tests/test_audio_processing.py tests/test_config_and_devices.py tests/test_speech_output.py -q`

Run: `python -m py_compile main.py gui.py audio_processing.py app_config.py device_utils.py speech_output.py login.py hotkeys.py model_loading.py`

Expected: all commands exit 0.
