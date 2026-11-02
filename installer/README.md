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

- Portable ZIP: `output\TranslitoPortable-1.0.5.zip`
- Installer: `output\TranslitoSetup-1.0.5.exe`

Pass `-BuildRoot <path>` to keep the virtual environment, PyInstaller files, and `output/` on another drive. Use a short path such as `D:\TranslitoBuild`; deeply nested Windows paths can exceed Inno Setup's file path limit.

The unpacked release is staged under `.packaging\release-dist` inside the build root; this keeps builds isolated from any older portable copy that may currently be running.

Settings are saved to `%LOCALAPPDATA%\Translito\config.ini`, independently of the installation folder or launch directory. On first save, existing settings beside the executable or in the legacy working folder are preserved. User settings take precedence on subsequent launches.

Models are not bundled. Whisper and Helsinki-NLP models download on first run and then use the Hugging Face cache. On Windows, downloads validate HTTPS certificates against the Windows certificate store.

The quality branch bundles the official unchanged VB-CABLE Pack45 ZIP. Its
optional installer task starts unchecked, requires explicit consent and verifies
the archive and setup hashes before an elevated vendor child runs. Translito's
installer stays unprivileged. See [setup/licensing](../docs/quality/VIRTUAL_MIC.md).

Listen's optional App audio source uses a bundled x64 in-memory WASAPI bridge,
with no driver or original-audio file. Its source is `native_windows/process_loopback.cpp`.
To rebuild it with Visual Studio C++ tools and a recent Windows SDK, run
`./build_process_loopback.ps1 -BuildRoot D:\TranslitoNativeBuild`.
This updates its binary/source SHA-256 manifest; run the process-audio tests before
packaging. The normal build collects the pinned DLL and notices under
`engines/data/windows`. The API needs Windows build 20348 or later.

Unsigned installers can trigger SmartScreen. Users can choose "More info" and "Run anyway", or the installer can be signed later with a code-signing certificate.
