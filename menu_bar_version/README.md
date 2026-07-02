# Desktop Audio Translator Menu Bar

This is a separate menu-bar version of the macOS translator. It does not replace
the existing `macos_version/Desktop Audio Translator.app`.

## What It Does

- Adds an `AT` item to the macOS menu bar.
- Click `AT` to open a lightweight menu-bar panel with **Settings** collapsed by
  default.
- Lets you choose audio device, speech language, target language, Whisper model,
  and offline mode by expanding **Settings**.
- Starts and stops translation directly from the collapsed panel.
- Shows translated text in a floating subtitle overlay near the bottom of the
  screen.
- Translation keeps running from the menu-bar app after the panel is hidden.
- Can toggle **Open at Login** for this menu-bar app.
- Keeps preferences and transcripts in:

```text
~/Library/Application Support/Desktop Audio Translator Menu Bar/
```

## Build The DMG

From this folder:

```bash
./build_dmg.sh
```

The output is:

```text
dist/Desktop_Audio_Translator_Menu_Bar.dmg
```

## Install

1. Open `dist/Desktop_Audio_Translator_Menu_Bar.dmg`.
2. Drag `Desktop Audio Translator Menu Bar.app` to `Applications`.
3. Open it from Applications.
4. Click `AT` in the menu bar to open the control panel.
5. Expand **Settings** only when you need to change device/model/language.

The app uses your installed Python 3 and Python packages, like the existing app.
If dependencies are missing, install them with:

```bash
python3 -m pip install -r src/requirements.txt
```

On a new machine, install BlackHole and grant Microphone permission just like the
standard macOS app.

## Open At Login

Click `AT`, expand **Settings**, then enable **Open at Login**. macOS may ask
for permission to let the app manage Login Items through System Events.

## Subtitles

When translation is running, the latest translated line appears in the subtitle
overlay even when the panel is hidden. Expand **Settings** and use
**Show subtitles** to show or hide it.

## BlackHole Audio Routing

For YouTube or other desktop audio, select `BlackHole 2ch` in the app and route
macOS audio into BlackHole:

1. Open **Audio MIDI Setup**.
2. Create a **Multi-Output Device** with your speakers/headphones and
   `BlackHole 2ch` checked.
3. Set macOS sound output to that Multi-Output Device.
4. Keep `BlackHole 2ch` selected as the app's audio input.

If BlackHole is present but silent, the subtitle overlay will now say
`No audio from BlackHole 2ch` instead of staying on `Listening`.
