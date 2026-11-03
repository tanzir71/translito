# Translito

A desktop audio transcription and translation app for Windows and macOS. The
Windows edition understands a conversation as English plus one other language,
passes through lines already in your language, and protects English technical
terms in mixed speech. Listen captures a device or one app; Speak sends translated
speech to a virtual microphone. Local processing works without a cloud key.

## Downloads

**Model management:** Settings → **Manage models…** lists available and downloaded
speech/translation models, disk use and cache locations. Choose **Downloaded**,
select a model and click **Delete model…** above the list to review and remove
that cached copy. Download and Open folder are alongside it. Model changes
require an idle session; gated models retain their
terms/token setup. See [model-manager details](docs/quality/MODEL_MANAGER.md).

- **Windows 1.1.5:** [Installer](https://github.com/tanzir71/translito/releases/download/v1.1.5/TranslitoSetup-1.1.5.exe), [portable ZIP](https://github.com/tanzir71/translito/releases/download/v1.1.5/TranslitoPortable-1.1.5.zip) or [checksums](https://github.com/tanzir71/translito/releases/download/v1.1.5/SHA256SUMS.txt). Keeps model download/delete controls visible above the list in compact windows. Includes model cache management, installer space/runtime checks, the Windows audio-thread fix, bilingual routing, optional free cloud providers, guided virtual-mic setup, app-audio capture and settings/certificate fixes.
- **macOS 1.0:** [Universal DMG](https://github.com/tanzir71/translito/releases/latest/download/Translito.dmg).

For the portable build, extract the entire ZIP into a new empty folder before
running `Translito.exe`. Use the installer for an in-place upgrade: it preserves
the previous runtime in `runtime-history` and installs fresh engine files, avoiding
old dependency metadata conflicts. Settings and transcripts keep their locations.

## Windows Feature Parity Update

The Windows GUI now includes Speak Mode and the native macOS parity work:

- **Speak Mode**: speak into a real microphone, translate your speech, and play the translated voice to a selected playback device.
- **VB-Cable routing**: choose `CABLE Input (VB-Audio Virtual Cable)` as the app output, then choose `CABLE Output (VB-Audio Virtual Cable)` as the microphone in Slack, Zoom, Teams, or Meet. Use headphones.
- **Model preload and progress**: the GUI starts loading the selected Whisper and translation models after launch, shows download/preparing status, and reuses the same load if Start is pressed mid-preload.
- **Lower latency**: chunks emit early when speech is followed by a pause, while steady room noise still waits for the normal window.
- **Live results**: recognized speech appears before translation completes. Speech boundaries assemble complete thoughts; waiting speech is retained with a lag indicator when processing falls behind. Stop cancels generation and clears the stopped session's pending audio.
- **Mic noise gate**: the Settings area includes an RMS gate slider from Off to High; it applies only to real microphones, never loopback or virtual sources.
- **Route recovery**: Speak Mode resolves output devices by name at playback time and retries once after PortAudio route errors.
- **Device refresh**: input/output pickers refresh automatically every few seconds and still include a manual Refresh button.
- **Global hotkeys**: defaults are `Ctrl+Alt+T` toggle, `Ctrl+Alt+L` listen, `Ctrl+Alt+S` speak, and `Ctrl+Alt+X` stop. Hotkeys are recordable in the GUI.
- **Open at login**: the Windows toggle writes the app command to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
- **Installer assets**: `installer/` contains PyInstaller and Inno Setup files for a one-dir app installer.

Windows 1.1.5 bundles the unmodified official VB-CABLE
package as an **optional, unchecked** installer component. The app's Speak setup
also offers explicit driver-install consent, a local routing test, and meeting-app
guides. Listen Mode needs no virtual cable. VB-CABLE is **donationware by
[VB-Audio](https://vb-audio.com/Cable/)**; users can
[donate or review licensing](https://vb-audio.com/Services/licensing.htm).
Organizations whose users cannot see or pay for VB-CABLE need the appropriate
VB-Audio license. See [virtual-mic setup and verification](docs/quality/VIRTUAL_MIC.md).

## Windows quality profiles

Choose a profile in Settings → Translation engine. The Free default processes
locally until you explicitly enable a cloud provider, add its key and pass Test.
Keys stay in Windows Credential Manager. Switching to Offline prevents inference
and download network access once the selected models are cached.

| Profile | Recognition and translation | Setup |
|---|---|---|
| Free (recommended) | Cached local Cohere Arabic if ready and fast enough, configured free ASR fallbacks, then local Whisper; configured free text translators, then local MT. | No key required. Azure F0 is the first optional text translator. |
| Offline (private) | Local recognizers and optional TranslateGemma, with Marian fallback. | Cache models first. Cohere/Gemma downloads require their respective terms/consent. |
| Custom | Enabled and tested providers in the configured routing order. | Each cloud provider requires its own setup/Test. |
| Live interpreter (Gemini preview) | Opt-in streaming speech/text translation with Free recovery. | A tested free-tier key and separate data-reuse consent; one-way preview, with real meeting timing/quality still unverified. |

The paid booster candidates are evaluation work only. No paid booster is selected
or enabled in this release, and the default monthly paid cap is $0. Private Saudi
meeting clips were unavailable and their evaluation was waived; public/synthetic
smoke tests do not establish Saudi accuracy or the target meeting latency.

Conversation controls are **English +**, **My language** for Listen, and
**Audience** for Speak. Settings offers both-language captions, protected English
terms, an editable glossary and original-voice/mute/voice handling when your
speech already matches the audience. Advanced one-way pairs remain available.

## Optional free cloud keys

Cloud providers start disabled. Open Settings → provider setup, read its data
notice, enter a key, choose the correct account tier, press Test and enable it.
Test sends a short public sample, never a current meeting. A changed key, region,
tier or consent requires a new Test. Provider errors and exhausted limits fall
back visibly to the next eligible engine.

**Azure Translator F0:** Create a Translator resource with the F0 pricing tier in
the [Azure portal](https://portal.azure.com/), then copy a key and its region from
the resource's Keys and Endpoint page. Confirm F0 in Translito. Its
[free allowance](https://azure.microsoft.com/en-us/pricing/details/translator/)
is 2 million characters per month. This is the recommended first text provider;
an S1 resource is not treated as F0.

**DeepL API Free (existing accounts):** If you already have this legacy API plan,
obtain its key in your [DeepL account](https://www.deepl.com/account/summary).
Free API keys end in `:fx`; Translito uses the Free endpoint with the legacy
500,000-character monthly limit. DeepL's [current plan page](https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans)
says API Free is no longer available to new subscribers. Its new Developer trial
has a lifetime allowance and is not represented by this adapter's monthly plan;
use Azure F0 for the recommended free setup. The desktop writing subscription is
also separate from the API plan.

**Google Cloud Translation Basic:** Enable the Cloud Translation API in your
[Google Cloud project](https://console.cloud.google.com/) and create an API key
restricted to that API. Basic uses a
[monthly character credit](https://cloud.google.com/products/translate/pricing)
covering the first 500,000 NMT characters. The project can bill beyond its credit;
usage outside Translito shares that account allowance. Translito's ledger covers
only its own calls, so also configure account quotas/billing controls yourself.

**Groq speech recognition:** Create a free developer API key in the
[Groq console](https://console.groq.com/keys), confirm the free tier and Test it.
The [published limits](https://console.groq.com/docs/rate-limits) vary by model
and account; Whisper large-v3 is a fallback, not a recognizer trained for Saudi
Arabic/English mixing. Audio leaves your computer when this provider is active.

**Cohere Arabic trial:** Obtain a trial key in the
[Cohere dashboard](https://dashboard.cohere.com/), confirm trial status and Test.
The trial has [request limits](https://docs.cohere.com/v2/docs/rate-limits), and
its [data terms](https://cohere.com/privacy) allow reuse for research/improvement;
personal information is not intended for trial use. It requires separate reuse
consent. Use cached local Cohere for private meetings once you have accepted the
model's gated download terms.

**Gemini free text / Live preview:** Create a Gemini API key in
[Google AI Studio](https://aistudio.google.com/apikey). Each provider card requires
free-tier confirmation, Test and separate reuse consent; free-tier inputs/outputs
may be used to improve Google's products under its
[API terms](https://ai.google.dev/gemini-api/terms). Live Translate remains an
optional preview. Paid account pricing is not silently inferred from a free key.

## Privacy and local data

| Engine or action | What leaves this computer | Stored locally |
|---|---|---|
| Offline/local ASR, MT and TTS | No inference data; explicit model setup downloads model files. | Cached models and transcripts. |
| Azure / DeepL / Google text MT | Text to translate, protected terms and adapter context where supported; no captured audio. | Usage totals, reservations and glossary-cache hashes; no raw keys in logs/config. |
| Cohere API / Groq ASR | Speech segments and the configured language/hotword hints. | Usage totals and generated transcripts. |
| Gemini text | Text, recent context and glossary data. Free-tier reuse consent is required. | Usage totals and generated transcripts. |
| Gemini Live preview | Captured audio and session/language instructions; receives translated text/speech. Free-tier reuse consent is required. | Usage totals and transcripts; resume handles stay in memory. |
| App-audio capture / virtual-mic self-test | No data is uploaded. | Audio stays in memory; original-audio files are not written. |

Settings live in `%LOCALAPPDATA%\Translito\config.ini`; API keys are in Windows
Credential Manager. `usage.json` retains UTC-month history, including conservative
reservations for uncertain request outcomes. Transcripts save as new files and
existing files are preserved. Usage/caps describe Translito's requests, not other
applications sharing the same provider account. See
[provider contracts](docs/quality/CLOUD_CONTRACTS.md) and
[implementation/verification limits](docs/quality/IMPLEMENTATION_STATUS.md).

## Features

### 🎤 Audio Capture
- **Desktop Audio**: Capture system audio (YouTube, music, calls, etc.) using loopback devices
- **Microphone Input**: Capture from any connected microphone
- **Device Selection**: Interactive device selector with auto-detection
- **Device Persistence**: Remembers your preferred audio device

### 🗣️ Speech Processing
- **Offline ASR (Default)**: Whisper with fast CPU inference via CTranslate2, or Transformers on CUDA (downloads the selected model once)
- **Speech activity filtering**: Drops silence and background noise before recognition
- **Multi-language**: Select source and target language in the GUI
- **Translation engines**: local Marian/optional TranslateGemma, with opt-in free cloud text providers
- **Continuous Processing**: Processes audio in short chunks (configurable) for near real-time results

### 🖥️ Simple GUI (Recommended)
- **Start/Stop** controls
- **Device picker** with refresh
- **Language selection** (speech source + translation target)
- **Download models** button for the selected languages (then run offline)

### ⌨️ CLI Keyboard Shortcuts
- **Ctrl+D**: Change audio device during transcription (CLI mode)
- **Ctrl+C**: Stop transcription (CLI mode)

### 💾 Session Management
- **Auto-save Transcripts**: Automatically saves all transcriptions when program closes
- **Readable Format**: Saves transcripts as formatted text files
- **Session Tracking**: Includes timestamps, device info, and session duration
- **Organized Storage**: Saves transcripts in dedicated `transcripts/` folder

## Installation

### Prerequisites
- Python 3.13 for the tested Windows source/build environment
- Windows operating system (desktop audio capture via loopback devices)
- Internet connection only for first-time model downloads (Whisper + translation models)
- Tkinter (for the GUI; included with most Python installations)

### Step 1: Clone or Download
```bash
git clone https://github.com/tanzir71/translito.git
cd translito
```

### Step 2: Install Dependencies
```bash
# Install required packages
pip install -r requirements.txt
```

### Optional: Enable NVIDIA GPU (CUDA) for Faster Whisper/Translation
If you see `CUDA not available (CPU-only torch build)`, you installed a CPU-only build of PyTorch.

```bash
pip uninstall -y torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

### Step 3: First Run
```bash
python gui.py
```

## Usage

### GUI (Recommended)
1. Run: `python gui.py`
2. Select audio device
3. Choose English plus your conversation's other language, then My language
4. (Optional) Click **Download models** to cache them for offline use
5. Click **Start**

### CLI
1. Run: `python main.py`
2. Select your audio device from the interactive menu (or press Enter to use the saved device)
3. Use:
   - **Ctrl+D**: Change device
   - **Ctrl+C**: Stop and save transcripts

### Offline Mode
After models are downloaded once, you can prevent any network access:
```powershell
$env:OFFLINE_ONLY="1"
python main.py
```

### Language Selection
The GUI defaults to an English-plus-other conversation, with separate My language
and Audience choices. Advanced one-way pairs keep independent source/target
selection for conversations without English.

For CLI, set:
- `ASR_LANGUAGE` to control recognition locale (e.g. `ar-AR`, `en-US`)
- `TRANSLATION_MODEL` to select the translation model (e.g. `Helsinki-NLP/opus-mt-en-ar`)

Example:
```powershell
$env:ASR_LANGUAGE="ar-SA"
python main.py
```

### Whisper Model Selection (Offline)
Whisper speed/accuracy depends on model size. On CPU, prefer smaller models:

CPU installations use an optimized copy of the selected Whisper model, so the first run may download it even if an older Transformers copy is cached.

```powershell
$env:WHISPER_MODEL="openai/whisper-tiny"
python main.py
```

Common choices:
- `openai/whisper-tiny` (fastest)
- `openai/whisper-base`
- `openai/whisper-small` (default)

### Tuning Chunk Duration
Use Settings' CPU speed check to select an appropriate model/preset. Lite favors
latency; Balanced and Quality spend more work on recognition. Waiting speech is
retained with a Behind indicator rather than silently discarded. The default
segmenter closes on speech boundaries, with a maximum utterance duration;
increasing a legacy chunk setting is not a latency guarantee. CLI experiments
can still set the chunk preference:
```powershell
$env:CHUNK_DURATION="8"
python main.py
```

### Fixing Loopback + Whisper (Sample Rate)
Some Windows loopback devices work best when captured at 48kHz. The app will resample to 16kHz internally for ASR.

```powershell
$env:CAPTURE_SAMPLE_RATE="48000"
python main.py
```

### Audio Debugging
To print basic audio levels (peak/rms) periodically:
```powershell
$env:AUDIO_DEBUG="1"
python main.py
```

### Device Management
- **First time**: Select and confirm your preferred device
- **Startup**: Press Enter to use saved device, or choose a new one
- **During transcription**: Press Ctrl+D to change devices on-the-fly
- **Auto-save**: Any newly selected device becomes your new default

## Output Format

### Console Output
```
🎤 Arabic: مرحبا كيف حالك
🔤 English: Hello, how are you
--------------------------------------------------
```

### Saved Transcripts
Transcripts are saved as `transcript_YYYYMMDD_HHMMSS.txt` in the `transcripts/` folder:

```
============================================================
ARABIC AUDIO TRANSCRIPTION SESSION
============================================================
Session Start: 2025-01-06 20:51:08
Session End: 2025-01-06 21:15:32
Audio Device: Desktop Audio
Total Entries: 5
============================================================

[001] 20:52:15
----------------------------------------
🎤 Arabic:  مرحبا كيف حالك
🔤 English: Hello, how are you

[002] 20:53:22
----------------------------------------
🎤 Arabic:  أهلا وسهلا
🔤 English: Welcome
```

## Configuration

### Config File
Device and language preferences are stored in `config.ini`:
```ini
[DEVICE]
name = Your Selected Device Name

[LANGUAGE]
source = ar
target = en
whisper_model = openai/whisper-small
```

### Customization
Runtime settings are primarily controlled via environment variables:
- `OFFLINE_ONLY`: `1` to prevent downloads (use after models are cached)
- `WHISPER_MODEL`: e.g. `openai/whisper-tiny`
- `ASR_LANGUAGE`: e.g. `ar-AR`, `ar-SA`
- `TRANSLATION_MODEL`: e.g. `Helsinki-NLP/opus-mt-ar-en`
- `CHUNK_DURATION`: seconds per audio chunk
- `AUDIO_DEBUG`: `1` to print audio level diagnostics

## Troubleshooting

### Common Issues

**"No audio devices found"**
- Ensure your audio devices are properly connected
- Try running as administrator
- Check Windows audio settings

**"Speech recognition error"**
- If running offline-only, disable it for the first run so models can download: `set OFFLINE_ONLY=0`
- In the GUI, use **Download models** for your language pair

**Stuck on \"Listening...\"**
- If you selected a loopback device, make sure audio is actually playing through that output
- If you selected a microphone, ensure Windows microphone permission is enabled (Settings → Privacy & security → Microphone)
- Enable audio debug: `set AUDIO_DEBUG=1`
- For offline Whisper on CPU, expect slower processing; try `set WHISPER_MODEL=openai/whisper-tiny` and/or `set CHUNK_DURATION=8`

**"Translation model loading slowly"**
- First-time model download can take several minutes
- Subsequent runs will be faster
- Ensure stable internet connection

**"Keyboard shortcuts not working"**
- Try running as administrator
- Ensure no other applications are capturing global hotkeys

### Audio Device Issues

**Desktop audio not capturing**
- Select a "loopback" device, not a regular microphone
- Ensure the application you want to capture is playing audio
- Check Windows sound settings

**Poor transcription quality**
- Ensure clear audio input
- Adjust system volume levels
- Try different audio devices
- Speak clearly in Arabic

## Technical Details

### Dependencies
- **soundcard**: Audio device access and recording
- **numpy**: Audio data processing
- **faster-whisper / CTranslate2**: Efficient CPU Whisper recognition
- **transformers**: CUDA Whisper recognition and Helsinki-NLP translation models
- **silero-vad**: Speech activity filtering
- **torch**: ML backend (CPU or CUDA)
- **keyboard**: Global keyboard shortcuts (CLI)
- **configparser**: Configuration file management

### Architecture
- **Multi-threaded**: Separate threads for audio capture and processing
- **Real-time**: Continuous 3-second audio chunk processing
- **Persistent**: Device preferences and transcript storage
- **Modular**: Clean separation of concerns

### Supported Languages
- **GUI**: Multiple languages (select source/target; downloads the matching Helsinki model)
- **CLI**: Configure via `ASR_LANGUAGE` + `TRANSLATION_MODEL`

## License

This project is open source. Feel free to modify and distribute.

## Contributing

Contributions are welcome! Areas for improvement:
- Additional language support
- Better audio preprocessing
- GUI interface
- Cross-platform compatibility
- Offline translation models

## Support

For issues or questions:
1. Check the troubleshooting section
2. Ensure all dependencies are properly installed
3. Verify your audio device setup
4. Test with clear Arabic audio input
