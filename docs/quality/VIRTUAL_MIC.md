# Windows virtual microphone

Implemented on the quality-development branch; not yet shipped in a rebuilt
release. Listen Mode uses loopback and never needs VB-CABLE.

## Speak setup

1. Use **Install virtual mic** on the Speak setup card, or select the optional
   unchecked VB-CABLE task during installation. Review VB-Audio's terms and
   donation link. The confirmation starts only the verified vendor setup as an
   elevated child; Translito stays unprivileged. Windows may ask for administrator
   access and driver-publisher approval. Handle those Windows prompts yourself.
2. The app checks for CABLE Input every two seconds for up to two minutes, selects
   it and saves the Speak output. If it is missing, restart Windows when ready.
   The app never restarts automatically; Restart requires a button click and a
   second confirmation.
3. Run **Test virtual mic**, then use **Pick meeting mic** for Zoom, Teams, Slack,
   Meet, Discord or another app. Choose CABLE Output as the meeting microphone and
   keep headphones as the meeting speaker. Keep your real microphone in Translito.
   Confirm step 3 only after changing the meeting app yourself.

The card disappears once installation, the current run's routing test, and the
meeting-app confirmation are complete. **Virtual-mic setup** opens it again.
A routing test also runs before every Speak session, before loading models or
starting capture. A failed test leaves capture stopped and shows the setup card.

## Local test and device lifecycle

The test plays a 0.8-second 1 kHz tone with -12 dBFS peak only to CABLE Input,
while recording only CABLE Output at 48 kHz stereo. It measures RMS in the
950–1050 Hz band, taking the strongest channel rather than cancelling inverted
channels. At least -30 dBFS passes. No real microphone, transcript or cloud engine
is used. Failure offers Windows Sound settings to check mute/levels.

Regular output-name lookup does not reset PortAudio: resetting it when opening a
monitor used to invalidate the first active stream. Idle device refresh and the
post-install poll explicitly refresh enumeration. A failed output write closes
both of the player's streams before refreshing/reopening them, preserves equal
playback duration, retries only the failed route's block and respects Stop.
Device auto-refresh pauses throughout setup, self-test and model startup.

## Package and licensing

The official ZIP is redistributed unchanged under `installer/redist/vbcable`.
Its vendor readme and all archive files remain intact. Archive size/SHA-256 is
checked before extraction; the x64 setup executable has a separate SHA-256 pin.
The Inno installer also verifies both hashes. Runtime never downloads a driver.
The Python manifest, installer hash and Inno literals are checked together.
Extracted setup files go in new uniquely named app-data directories; no existing
driver, extraction, user config or transcript is removed.

VB-CABLE is donationware by [VB-Audio](https://vb-audio.com/Cable/).
Its current [distribution/licensing terms and donation options](https://vb-audio.com/Services/licensing.htm)
permit bundling subject to the donationware conditions. Organizations where users
cannot identify/pay for the product need the appropriate license. A+B and C+D
packages are not included. Verified 2026-11-02.

## Evidence and remaining acceptance

- Pack45 downloaded directly from the vendor: 1,318,877 bytes,
  SHA-256 `b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb`.
  Windows reports a valid setup signature from BUREL VINCENT Entrepreneur
  individuel. This was read-only signature inspection.
- Tests verify intact extraction, tamper/path rejection before mutation,
  consent gates, timeout/cancel/success polling, no reboot without consent, tone
  analysis, virtual-only playback/capture, and the GUI pre-start success/failure
  gate without any real model or audio device. Output tests simulate both cable
  and monitor failures without duplicate audio intervals.
- Inno compiled the optional task/verification/extraction/elevation code using a
  README-only fixture. That compiler-check EXE cannot serve as an app installer.
- No CABLE device is installed on the development machine. No driver installer,
  UAC prompt, reboot or physical tone test was performed. Those checks, actual
  meeting-app routing, and rebuilt-app/installer verification remain outstanding.
- The full Python suite passes 285 tests. Real meeting-app/browser-child capture
  and rebuilt packaging are still unverified.

## App audio for Listen

Choose **App audio** beside Device, then select an app currently playing audio.
The picker checks active rendering sessions on all playback endpoints every
three seconds while idle. Browser utility/render processes are grouped under
their same-executable root. Capturing includes the selected process's children.
**All apps (exclude Translito)** excludes Translito and its child processes, so
its speech output cannot feed itself back into Listen.

A silent selected app stays selected with a “not playing” hint; automatic refresh
never switches it to All apps. A process creation-time check rejects a closed or
reused PID before capture. Silence returns bounded zero blocks so Stop remains
responsive. No original-audio file is written: a native PCM callback copies into
the existing in-memory desktop pipeline. There is no capture until Start.

The bundled 130 KB x64 bridge is built from `native_windows/process_loopback.cpp`
with MSVC/static CRT and an explicit ABI. Binary and source hashes are pinned;
runtime verifies the DLL, and packaging collects it with its notices. The public
process-audio-capture wrapper was inspected but not installed: it exposes levels
and WAV-file output rather than the PCM stream this app needs.

Microsoft's [application-loopback API](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)
requires Windows build **20348 or later**, including Windows 11. The UI enforces
that minimum and 64-bit Python; Device loopback remains available on older Windows.

A native smoke test played a synthetic 1 kHz tone in the test process: INCLUDE
captured max RMS 0.021198729, EXCLUDE reduced it to 0.000014638, and active-session
enumeration found its PID. Both native workers stopped and released their events.
This verifies the API/format/stop path on this machine, not real call quality or
meeting-app child-process behavior. No microphone, saved raw audio, or cloud
inference was involved. Tests also check native PCM copy ownership, frame splitting,
silence, startup failure cleanup, browser grouping, PID reuse, self-exclusion and
retaining a silent selection in the actual GUI refresh method.

## Meeting menu references

Menu paths checked against primary help pages on 2026-11-02:
[Zoom](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0060836),
[Teams](https://support.microsoft.com/en-us/teams/notifications-settings/manage-your-device-settings-in-microsoft-teams),
[Slack](https://slack.com/help/articles/1500002037922-Adjust-your-huddles-preferences),
[Meet](https://support.google.com/meet/answer/10409699?hl=en-EN),
[Discord](https://support.discord.com/hc/en-us/articles/33030151293079-Discord-Voice-Video-Streaming-Guide).
The guide provides direct links; menu wording may vary by app version.
