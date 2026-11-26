# Windows 2.0.2

The main window's Set up cloud and Keep using this PC actions share one row with
equal button dimensions. Cloud setup groups the full-width key field with one
action row. Connect becomes Check connection for a saved key and Save new key
when a replacement is entered. Remove key appears only for a saved credential;
the duplicate Replace key actions and empty status card are removed. Controls
show connection progress and prevent duplicate requests while a check is active.

Speak Mode automatically selects an available CABLE Input. Device polling keeps
a subsequent explicit output choice. Normal onboarding is a neutral Speak Mode
setup card that stays hidden when the cable is selected. A routing failure still
blocks startup and shows recovery actions; the cable-only self-test still runs
before every Speak session. Installer driver consent stays optional and unchecked.

The main window opens at the center of its monitor's usable area. Child dialogs
center over their visible parent and stay inside that monitor's work area. Model
and virtual-mic dialogs use the same placement helper, and dialog dimensions are
scaled once rather than twice at higher DPI.

## Windows warning

Read-only Authenticode inspection reports NotSigned for both the existing
2.0.0 and 2.0.1 installers. No Translito signing identity is configured. The new
installer remains unsigned; these UI fixes do not promise to remove SmartScreen.
Microsoft checks file, URL and publisher reputation, so an unfamiliar new build
can warn even when a previous build did not. Authenticode signing with a trusted
publisher identity is the appropriate next step, and it does not guarantee an
immediate SmartScreen reputation change.

Source: [Microsoft Defender SmartScreen](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen).

## Verification

- Final serialized source suite: **809 passed**, with one existing Torch
  deprecation warning. Real Tk checks cover equal button geometry, Speak default
  selection, manual-choice retention, setup states and layout at 150% scaling.
- The frozen executable passed all **19** dependency checks.
- The portable ZIP passed a complete CRC check. Every packaged engine data file
  and all VB-CABLE redistribution files match their sources.
- Bytecode inspection confirms all five changed UI modules in the actual frozen
  EXE/PYZ match the final source, excluding only source-location metadata.
- Hugo's **64** site checks pass with the 2.0.2 download links.
- No real keys, paid inference, driver installation or physical audio were used.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.2.exe | 256,859,832 | `39d75f9312ce39e543c8a518bf93d6d0ce8b30c07da0440ed8b3d572bd9583d6` |
| TranslitoPortable-2.0.2.zip | 374,048,894 | `08a940f841bf43e62c2a86809b6128917b403e1fa4fca9b0c1d187213fd18ce7` |
| Translito.dmg | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |

The macOS DMG is the retained 1.0 build. The new Windows installer and app both
report version 2.0.2 and remain unsigned. Runtime, package/source and signing
reports, the dependency snapshot and SHA-256 manifests accompany the release.
