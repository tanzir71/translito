# macOS Desktop Audio Translator

A macOS version of the desktop audio translator with the same local-model approach as the Windows app. It captures microphone or desktop audio, transcribes speech locally with Whisper via Transformers, and translates with Helsinki-NLP models. The GUI is the recommended entrypoint.

## Features

### Audio Capture
- Desktop audio capture through BlackHole or another virtual audio device
- Microphone capture from any available input
- Device picker with saved default device
- BlackHole/virtual devices are prioritized in the GUI

### Local Speech And Translation
- Offline Whisper ASR by default after the model is downloaded once
- Helsinki-NLP translation models downloaded per language pair
- Source and target language selection in the GUI
- Optional offline-only mode to prevent network access
- Apple Silicon MPS acceleration when supported by the installed PyTorch build

### GUI App
- Double-click `Desktop Audio Translator.app`
- Select device, source language, target language, and Whisper model
- Download models ahead of time
- Start/Stop live transcription
- View live source and translated text

### CLI
- Run `python3 main.py`
- Select a saved or new audio device in the terminal
- Cmd+D attempts to request a device change during transcription
- Cmd+C stops and saves the transcript

## Installation

### Prerequisites
- macOS 10.14 or newer
- Python 3.8 or newer
- Tkinter for the GUI, usually bundled with python.org Python
- Xcode Command Line Tools if native packages need compilation:

```bash
xcode-select --install
```

### Install Python Dependencies

From this folder:

```bash
cd macos_version
python3 -m pip install -r requirements.txt
```

The app no longer uses PyAudio or SpeechRecognition for transcription. Whisper and translation both run locally through Transformers after first download.

### Install BlackHole For Desktop Audio

BlackHole lets macOS route system audio into an input device the app can record.

```bash
brew install blackhole-2ch
```

Or install it manually from the BlackHole project page.

### Create A Multi-Output Device

Use this when you want to hear desktop audio while the app captures it.

1. Open **Audio MIDI Setup**.
2. Click **+** and choose **Create Multi-Output Device**.
3. Enable both **BlackHole 2ch** and your speakers/headphones.
4. Put your speakers/headphones first when possible.
5. Set the Multi-Output Device as the macOS sound output.
6. In the translator app, select **BlackHole 2ch** as the capture device.

### Grant Permissions

For microphone or BlackHole input capture:

1. Open **System Settings > Privacy & Security > Microphone**.
2. Enable access for Terminal, your Python launcher, or your IDE.
3. Restart the app after changing permissions.

For CLI Cmd+D device switching:

1. Open **System Settings > Privacy & Security > Accessibility**.
2. Enable access for Terminal, your Python launcher, or your IDE.

The GUI Start/Stop controls do not need global keyboard shortcuts.

## Usage

### GUI

Double-click `Desktop Audio Translator.app` in Finder. It opens the GUI directly without requiring a Terminal command.

1. Choose **BlackHole 2ch** or another virtual device for desktop audio, or choose a microphone.
2. Choose the speech source language and translation target.
3. Choose a Whisper model. On CPU, start with `openai/whisper-tiny` or `openai/whisper-base`.
4. Click **Download models** once if you want to cache models before going offline.
5. Click **Start**.

If macOS blocks the app bundle or you need a visible launch log, double-click `Launch Translator.command`.

Terminal fallback:

```bash
cd macos_version
python3 gui.py
```

### CLI

```bash
cd macos_version
python3 main.py
```

The CLI uses the same local Whisper and translation models as the GUI. Language/model selection is controlled by environment variables.

## Offline Mode

After models are downloaded once:

```bash
export OFFLINE_ONLY=1
python3 gui.py
```

The GUI also has an **Offline mode (no downloads)** checkbox.

## Configuration

Preferences are stored next to the mac app in `macos_version/config.ini`.

```ini
[DEVICE]
name = BlackHole 2ch

[LANGUAGE]
source = ar
target = en
whisper_model = openai/whisper-small
```

Runtime options:

- `OFFLINE_ONLY=1`: prevent Hugging Face downloads
- `WHISPER_MODEL=openai/whisper-tiny`: choose the CLI Whisper model
- `ASR_LANGUAGE=ar-AR`: choose the CLI recognition language
- `TRANSLATION_MODEL=Helsinki-NLP/opus-mt-ar-en`: choose the CLI translation model
- `CHUNK_DURATION=8`: change audio chunk duration in seconds
- `CAPTURE_SAMPLE_RATE=48000`: force the capture sample rate
- `AUDIO_DEBUG=1`: print audio level diagnostics

## Output

Console and GUI entries show the source text and translation:

```text
Source: مرحبا كيف حالك
Target: Hello, how are you
```

Transcripts are saved in `macos_version/transcripts/` as `transcript_YYYYMMDD_HHMMSS.txt`.

## Troubleshooting

### No desktop audio is captured

- Confirm macOS output is set to the Multi-Output Device.
- Confirm the Multi-Output Device includes BlackHole and your speakers/headphones.
- Select **BlackHole 2ch** in the app, not the Multi-Output Device.
- Play audio before starting transcription.
- Try `CAPTURE_SAMPLE_RATE=48000`.

### No audio devices are listed

- Check that Microphone permission is granted to Terminal/Python.
- Restart Terminal after granting permission.
- Confirm BlackHole appears in Audio MIDI Setup if you need desktop audio.

### Model download or startup is slow

- First-time Whisper and translation downloads can take several minutes.
- Use `openai/whisper-tiny` or `openai/whisper-base` on CPU.
- On Apple Silicon, install a current PyTorch build so MPS acceleration is available.

### Offline mode fails to start

- Disable offline mode once and click **Download models** for the selected Whisper model and language pair.
- Re-enable offline mode after the download completes.

## Technical Details

- **soundcard**: macOS audio device access
- **transformers**: Whisper ASR and Helsinki-NLP translation
- **torch**: CPU, CUDA, or Apple MPS execution
- **tkinter**: GUI
- **keyboard**: optional CLI global shortcut support
