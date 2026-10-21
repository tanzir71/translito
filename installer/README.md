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

- Portable ZIP: `output\TranslitoPortable-1.0.2.zip`
- Installer: `output\TranslitoSetup-1.0.2.exe`

Pass `-BuildRoot <path>` to keep the virtual environment, PyInstaller files, and `output/` on another drive. Use a short path such as `D:\TranslitoBuild`; deeply nested Windows paths can exceed Inno Setup's file path limit.

The unpacked release is staged under `.packaging\release-dist` inside the build root; this keeps builds isolated from any older portable copy that may currently be running.

Models are not bundled. Whisper and Helsinki-NLP models download on first run and then use the Hugging Face cache. On Windows, downloads validate HTTPS certificates against the Windows certificate store. VB-Audio Virtual Cable is not bundled; the installer offers the download page after setup.

Unsigned installers can trigger SmartScreen. Users can choose "More info" and "Run anyway", or the installer can be signed later with a code-signing certificate.
