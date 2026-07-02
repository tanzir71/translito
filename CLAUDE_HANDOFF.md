# Claude Handoff: Native macOS Audio Translator

Date: 2026-07-02

## Goal

Build a fully native macOS version in Xcode that matches the working Windows app's behavior: capture desktop or microphone audio, transcribe locally, translate locally, show live output, and save transcripts.

The Windows version is the working reference. The macOS implementation should not be a literal port of the Windows audio-capture path because accurate desktop audio capture works differently on macOS.

## Read These First

Use these repo files as context:

- `README.md`: working Windows app behavior and user docs.
- `main.py`: source of truth for the current runtime pipeline.
- `gui.py`: source of truth for the current GUI flow.
- `requirements.txt`: Windows/Python dependencies.
- `macos_version/main.py`: current macOS Python adaptation.
- `macos_version/gui.py`: current macOS GUI adaptation.
- `macos_version/README.md`: current macOS routing and permission docs.
- `menu_bar_version/README.md`: current menu-bar app behavior and subtitle overlay notes.
- `menu_bar_version/app/Contents/Resources/menubar_app.py`: existing menu-bar control pattern.

Avoid treating `dist/`, `.app` bundles, `__pycache__/`, `.DS_Store`, screenshots, and generated website output as implementation source unless explicitly needed.

## Current Working Windows Behavior

The root app is the working version.

- Uses Python `soundcard` for audio devices.
- Calls `sc.all_microphones(include_loopback=True)`.
- Separates desktop audio by `device.isloopback`.
- Captures loopback at 48 kHz by default, microphone at 16 kHz.
- Converts stereo to mono.
- Resamples everything to 16 kHz before Whisper.
- Processes 6 second chunks by default.
- Uses peak/rms silence detection and applies gain to quiet chunks.
- Uses Transformers Whisper for offline ASR.
- Uses Helsinki-NLP translation models.
- Saves transcripts under `transcripts/`.
- Persists device/language/model choices in `config.ini`.

Important Windows reference points:

- `main.py` -> `ArabicAudioTranscriber.capture_audio`
- `main.py` -> `ArabicAudioTranscriber.process_audio`
- `main.py` -> `select_audio_device`
- `gui.py` -> device/language/model selection and start/stop behavior

## Current macOS Python State

`macos_version/` and `menu_bar_version/` are Python adaptations, not the final native direction.

The macOS Python path uses:

- `soundcard` for microphone and virtual input devices.
- Virtual-device name detection for `BlackHole`, `Soundflower`, `Loopback`, `Background Music`, `VB-Cable`, `Audio Hijack`, `Rogue Amoeba`, and generic `virtual`.
- 48 kHz capture for desktop/virtual devices, then 16 kHz ASR.
- Apple Silicon MPS when available through PyTorch.
- BlackHole routing instructions because macOS does not expose Windows-style loopback recording through `soundcard`.

The current macOS app works by making desktop audio appear as an input device. For example:

1. Install BlackHole 2ch.
2. Create a macOS Multi-Output Device containing BlackHole and the user's speakers/headphones.
3. Set macOS output to that Multi-Output Device.
4. Select `BlackHole 2ch` as the app input.

This is a useful fallback, but it is not the ideal native Xcode capture architecture.

## Key Platform Difference

Windows:

- Desktop audio can be captured as a loopback input through `soundcard`.
- `device.isloopback` is meaningful for the working app.
- The user can often choose a loopback device directly.

macOS:

- Built-in Core Audio input devices are not equivalent to Windows loopback devices.
- `soundcard` is fine for microphones and virtual devices, but it is not the native solution for direct desktop/system audio capture on macOS.
- Accurate desktop capture needs either an Apple native capture API or a virtual audio driver.

Do not port the Windows `soundcard` loopback model 1:1 into the native Mac app.

## Native macOS Capture Recommendation

Use a capture abstraction so the UI and transcription pipeline do not care which backend is active:

```text
AudioCaptureService
  -> ScreenCaptureKitSystemAudioCapture
  -> CoreAudioProcessTapCapture
  -> AVAudioEngineInputDeviceCapture
```

Recommended order:

1. Implement `ScreenCaptureKitSystemAudioCapture` first for modern macOS system audio capture.
2. Keep `AVAudioEngineInputDeviceCapture` for microphones and virtual devices such as BlackHole.
3. Prototype `CoreAudioProcessTapCapture` if the deployment target supports it and audio-only capture without a screen stream is a hard requirement.

### Option A: ScreenCaptureKit

Use ScreenCaptureKit for the native system audio path.

Expected shape:

- Request/verify Screen Recording permission.
- Fetch shareable content.
- Build an `SCContentFilter` for a display or chosen content source.
- Configure `SCStreamConfiguration`.
- Set `capturesAudio = true`.
- Set `excludesCurrentProcessAudio = true` if the app should not capture its own speech/alert sounds.
- Add a stream output for `.audio`.
- Convert audio `CMSampleBuffer` data into the pipeline's internal PCM format.

Why:

- Public Apple framework for high-performance screen and audio capture.
- Avoids requiring BlackHole for users on supported macOS versions.
- Fits a native Swift/Xcode app better than Python `soundcard`.

Tradeoffs:

- Requires Screen Recording permission even if the product only cares about audio.
- Needs careful permission onboarding in the UI.
- The capture code must handle `CMSampleBuffer` audio formats, channel counts, and route changes.

### Option B: Core Audio Process Taps

Consider Core Audio taps if targeting a sufficiently new macOS version and the product needs a more audio-native system/process capture path.

Expected shape:

- Use `CATapDescription`.
- Create a tap with `AudioHardwareCreateProcessTap`.
- Feed the tap through the HAL/aggregate-device style shown in Apple's sample.
- Expose the resulting PCM buffers to the same `AudioCaptureService` contract.

Why:

- Apple has a sample specifically for capturing system audio with Core Audio taps.
- Potentially a better fit for audio-only capture and per-process/system-output capture.

Tradeoffs:

- Lower-level and more fragile than ScreenCaptureKit.
- Newer API surface than the current Python app.
- Claude should verify the exact deployment target, permissions, sandboxing, signing, and App Store constraints before choosing this as the primary path.

### Option C: AVAudioEngine Input Capture

Use `AVAudioEngine` input taps for microphones and virtual audio devices only.

This is the native replacement for the current BlackHole fallback:

- Enumerate/select audio input devices.
- Capture from the selected input node/device.
- Install an input tap.
- Convert to mono Float32 PCM.
- Resample to 16 kHz for ASR.

This does not magically capture desktop audio from the default speaker output. It captures whatever is available as an input device. For desktop audio, that means BlackHole or a similar virtual driver must be routed first.

## Libraries And APIs That Actually Work For Accurate Desktop Audio

Use this decision table:

| Capture target | Recommended native path | Works without external driver | Notes |
| --- | --- | --- | --- |
| System/desktop audio on modern macOS | ScreenCaptureKit | Yes | Best first implementation for Xcode. Requires Screen Recording permission. |
| System/process audio on newer macOS | Core Audio Process Taps | Yes | Promising audio-native path. Verify deployment target and permission behavior. |
| Microphone input | AVAudioEngine / AVFAudio | Yes | Straightforward native input capture. |
| Desktop audio on older macOS or fallback mode | BlackHole + AVAudioEngine input capture | No | Reliable if the user routes system output to BlackHole correctly. |
| Windows desktop loopback | Current Python `soundcard` path | N/A | This is the working Windows reference, not the Mac model. |
| Python `soundcard` direct desktop loopback on Mac | Not recommended for native app | No | Useful only for virtual inputs like BlackHole in the current Python prototype. |

BlackHole notes:

- Good fallback for dev/test and older macOS support.
- The app should select the `BlackHole 2ch` input, not the Multi-Output Device.
- Do not bundle or embed BlackHole without reviewing its license. The upstream project states GPL-3.0 terms unless another license is arranged.

## Audio Pipeline Contract To Preserve

Whichever native capture backend is used, normalize the output into this shape before ASR:

```text
Float32 PCM
mono
16_000 Hz for ASR
6 second chunks by default
peak/rms silence detection
optional gain for low-level audio
```

Implementation details:

- Capture at the device/native sample rate, often 48 kHz for desktop/system audio.
- Downmix stereo/multichannel to mono.
- Resample to 16 kHz with `AVAudioConverter` or another high-quality native converter.
- Maintain timestamps or chunk sequence numbers so transcript ordering is stable.
- Keep a ring buffer or chunker that can emit fixed ASR windows while capture continues.
- Preserve the current transcript fields: source text, translated text, timestamp, device/source info.

## Native App Shape

Suggested Xcode architecture:

- SwiftUI or AppKit menu-bar app.
- Optional floating subtitle overlay, matching `menu_bar_version`.
- Clear status states: Ready, Loading models, Listening, Transcribing, Translating, No audio, Permission needed, Error.
- Device/source selector:
  - System Audio, backed by ScreenCaptureKit or Core Audio Tap.
  - Microphone, backed by AVAudioEngine.
  - Virtual Device, backed by AVAudioEngine and device selection.
- Settings:
  - source language
  - target language
  - ASR model
  - offline mode
  - transcript folder
  - exclude app audio toggle
- Permissions onboarding:
  - Screen Recording for ScreenCaptureKit.
  - Microphone for mic/virtual input.
  - Accessibility only if global shortcuts are kept. Prefer UI controls and system menu commands instead.

## ASR And Translation Notes

The Python app currently uses Transformers Whisper and Helsinki-NLP. A fully native app needs a native model story.

Possible native directions:

- Use a Swift-compatible Whisper runtime, such as whisper.cpp bindings or a Core ML based Whisper package.
- Use a local translation model runtime that can run in Swift, Core ML, or an embedded native library.
- If keeping a helper process temporarily, make it explicit as a bridge, not the final "fully native" target.

The handoff priority here is audio capture correctness. Preserve the existing ASR/translation behavior contract even if the native model implementation changes.

## Acceptance Criteria

Desktop/system audio:

- Captures audio playing in Safari/Chrome/YouTube with no microphone bleed.
- Does not capture the app's own notification or speech output when exclusion is enabled.
- Shows non-zero peak/rms levels while system audio is playing.
- Continues for at least 30 minutes without drift, silence lockup, or runaway buffering.
- Recovers gracefully if the default output device changes.
- Handles AirPods/Bluetooth output and built-in speakers.
- Shows actionable permission errors.

Microphone/virtual input:

- Captures built-in microphone.
- Captures BlackHole when the user routes output correctly.
- Shows a specific "No audio from BlackHole" style hint if the selected virtual device is silent.
- Does not tell the user to select the Multi-Output Device as the app input.

Processing:

- Converts capture to mono 16 kHz Float32 before ASR.
- Keeps chunking and transcript ordering stable.
- Saves transcripts in a human-readable format.
- Preserves source/target language selection.

Packaging:

- Builds from Xcode.
- Handles signing and permissions cleanly.
- Does not require Python for the final native target unless explicitly scoped as a temporary bridge.

## Pitfalls To Avoid

- Do not assume macOS has a `device.isloopback` equivalent like Windows.
- Do not use `AVAudioEngine` alone and expect it to record speaker output.
- Do not make BlackHole the only path if the goal is a polished native app for modern macOS.
- Do not capture at 16 kHz directly from desktop/system audio if the device/API naturally produces 48 kHz. Capture native, then resample.
- Do not mix UI state and capture callbacks directly. Push capture buffers/events through a service boundary.
- Do not block the capture callback with ASR or translation work.
- Do not write generated build products back into source-control handoff docs.

## Useful References

- Apple ScreenCaptureKit docs: https://developer.apple.com/documentation/screencapturekit/
- Apple `SCStreamConfiguration.capturesAudio`: https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/capturesaudio
- Apple Core Audio taps sample: https://developer.apple.com/documentation/coreaudio/capturing-system-audio-with-core-audio-taps
- Apple `CATapDescription`: https://developer.apple.com/documentation/coreaudio/catapdescription
- Apple AVAudioNode input taps: https://developer.apple.com/documentation/avfaudio/avaudionode/installtap%28onbus%3Abuffersize%3Aformat%3Ablock%3A%29
- BlackHole upstream project and license notes: https://github.com/ExistentialAudio/BlackHole

## Bottom Line For Claude

Treat root `main.py` and `gui.py` as the behavior spec. Treat `macos_version/` and `menu_bar_version/` as UX and fallback references.

For native Xcode desktop audio, start with ScreenCaptureKit. Keep AVAudioEngine for mic/BlackHole fallback. Consider Core Audio Process Taps only after confirming deployment target and permission constraints.
