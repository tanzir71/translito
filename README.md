# Desktop Audio Translator

A real-time desktop audio transcription and translation tool. Captures desktop audio or microphone input, transcribes speech locally using Whisper, and translates using Helsinki-NLP models. Includes both a GUI and a CLI.

## Windows Feature Parity Update

The Windows GUI now includes Speak Mode and the native macOS parity work:

- **Speak Mode**: speak into a real microphone, translate your speech, and play the translated voice to a selected playback device.
- **VB-Cable routing**: choose `CABLE Input (VB-Audio Virtual Cable)` as the app output, then choose `CABLE Output (VB-Audio Virtual Cable)` as the microphone in Slack, Zoom, Teams, or Meet. Use headphones.
- **Model preload and progress**: the GUI starts loading the selected Whisper and translation models after launch, shows download/preparing status, and reuses the same load if Start is pressed mid-preload.
- **Lower latency**: chunks emit early when speech is followed by a pause, while steady room noise still waits for the normal window.
- **Mic noise gate**: the Settings area includes an RMS gate slider from Off to High; it applies only to real microphones, never loopback or virtual sources.
- **Route recovery**: Speak Mode resolves output devices by name at playback time and retries once after PortAudio route errors.
- **Device refresh**: input/output pickers refresh automatically every few seconds and still include a manual Refresh button.
- **Global hotkeys**: defaults are `Ctrl+Alt+T` toggle, `Ctrl+Alt+L` listen, `Ctrl+Alt+S` speak, and `Ctrl+Alt+X` stop. Hotkeys are recordable in the GUI.
- **Open at login**: the Windows toggle writes the app command to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
- **Installer assets**: `installer/` contains PyInstaller and Inno Setup files for a one-dir app installer.

VB-Audio Virtual Cable is donationware and is not bundled. Download it from https://vb-audio.com/Cable/.

## Features

### 🎤 Audio Capture
- **Desktop Audio**: Capture system audio (YouTube, music, calls, etc.) using loopback devices
- **Microphone Input**: Capture from any connected microphone
- **Device Selection**: Interactive device selector with auto-detection
- **Device Persistence**: Remembers your preferred audio device

### 🗣️ Speech Processing
- **Offline ASR (Default)**: Whisper via Transformers (runs locally; downloads model once)
- **Multi-language**: Select source and target language in the GUI
- **High-Quality Translation**: Helsinki-NLP translation models (downloads once per language pair)
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
- Python 3.8 or higher
- Windows operating system (desktop audio capture via loopback devices)
- Internet connection only for first-time model downloads (Whisper + translation models)
- Tkinter (for the GUI; included with most Python installations)

### Step 1: Clone or Download
```bash
# Download the main.py file to your desired directory
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
3. Choose speech source language + translation target language
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
The GUI supports selecting source/target languages directly.

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

```powershell
$env:WHISPER_MODEL="openai/whisper-tiny"
python main.py
```

Common choices:
- `openai/whisper-tiny` (fastest)
- `openai/whisper-base`
- `openai/whisper-small` (default)

### Tuning Chunk Duration
If Whisper feels slow or “lags” behind, increase chunk duration:
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
- **transformers**: Whisper (offline ASR) and Helsinki-NLP translation models
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
