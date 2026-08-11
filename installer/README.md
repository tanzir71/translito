# Windows Installer

Run the release build from PowerShell:

```powershell
.\build_windows.ps1
```

The script creates an isolated CPU-only build environment, runs PyInstaller, packages the portable app, and wraps the result with Inno Setup. To rebuild without reinstalling dependencies:

```powershell
.\build_windows.ps1 -SkipDependencies
```

Outputs:

- Portable ZIP: `output\TranslitoPortable-1.0.0.zip`
- Installer: `output\TranslitoSetup-1.0.0.exe`

The unpacked release is staged under `.packaging\release-dist`; this keeps builds isolated from any older portable copy that may currently be running.

Models are not bundled. Whisper and Helsinki-NLP models download on first run and then use the Hugging Face cache. VB-Audio Virtual Cable is not bundled; the installer offers the download page after setup.

Unsigned installers can trigger SmartScreen. Users can choose "More info" and "Run anyway", or the installer can be signed later with a code-signing certificate.
