# Windows Installer

Build one-dir PyInstaller output first:

```powershell
python -m pip install -r ..\requirements.txt
pyinstaller DesktopAudioTranslator.spec --noconfirm --clean
```

Then build `DesktopAudioTranslator.iss` with Inno Setup.

Models are not bundled. Whisper and Helsinki-NLP models download on first run and then use the Hugging Face cache. VB-Audio Virtual Cable is not bundled; the installer offers the download page after setup.

Unsigned installers can trigger SmartScreen. Users can choose "More info" and "Run anyway", or the installer can be signed later with a code-signing certificate.
