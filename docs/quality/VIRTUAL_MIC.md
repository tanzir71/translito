# Windows virtual microphone

Included since Windows 1.1.0; the current public Windows release is 1.1.1.
Windows 1.1.3 is installed locally; public-release publication is pending. See the installation follow-up below.
Listen Mode uses loopback and never needs VB-CABLE.

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
monitor used to invalidate the first active stream. Idle polling leaves PortAudio
running. Manual refresh runs off Tk's thread; the post-install poll also refreshes
enumeration in the background. A failed output write closes
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
- The initial Inno compiler check used a README-only fixture. Deliverable Windows
  1.1.0 and 1.1.1 installers were subsequently rebuilt, installed and verified;
  see `RELEASE_1_1_0.md` and `RELEASE_1_1_1.md`.
- No CABLE device is installed. The owner approved installation and the tone
  test, and the installed app extracted the verified ZIP. Windows rejected the
  standard elevated launch with error 3 before a driver process started. A
  separate extraction with inherited folder permissions failed identically;
  the cause is unproven. Manual Windows installation is pending. No reboot or
  successful physical cable/meeting-app routing test is claimed.
- The latest full suite passed 351 tests. Rebuilt 1.1.1 playback displayed
  Arabic source and English target, saved on Stop, and returned to Ready. The
  installed copy opens normally with original settings/transcripts preserved.
  Real meeting sessions still need acceptance; the isolated browser-child
  capture check below establishes only its stated native path.

## Installation follow-up — 2026-11-03

After the app-data error-3 failures above, the same verified Pack45 launched
from a unique `C:\Temp\TranslitoVBCable-*` directory. The owner approved Windows
administrator consent and confirmed installation. The vendor GUI reported
success and requested a reboot. Initial source cable-only tone/capture checks
passed after correcting per-thread COM setup, but later packaged and source
tests stalled in Windows audio Start. Windows shows a working cable plus two
failed-start duplicate nodes. No restart/device removal occurred; stable routing
awaits reboot and retest. See [the 1.1.2 follow-up](RELEASE_1_1_2.md) for exact
scope, failed checks, source revision and preserved evidence.

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

### Isolated browser-child measurement — 2026-11-02

At source `3e47197c683969b42aea835c36540c0515e913ce`, installed Edge
156.0.4314.58 ran a local Web Audio 1 kHz oscillator at amplitude 0.03 in a new,
headless profile. The page was served only on loopback; it used no microphone,
meeting tab or external media. The Chromium [headless mode](https://developer.chrome.com/docs/automation-and-testing/headless)
and test-only [autoplay switch](https://developer.chrome.com/blog/autoplay#developer-switches)
apply to that isolated browser process. Existing browser profiles/settings were
not modified. Its temporary profile and all test artifacts are preserved.

The Windows audio session belonged to child PID 31584. The desktop
`active_sources()` function grouped it under browser root PID 22736. Selecting
that root through the real `ProcessSource`/`ProcessRecorder`/`NativeBridge` path
captured max RMS 0.021213483, with 0.021213477 in the 950–1050 Hz band. A separate
owned, silent sibling process captured max RMS 0.000014931 while the browser
tone continued. This verifies child-tree inclusion and isolation from that
sibling on this machine. It does not prove every browser/meeting app, full GUI
browser selection, call quality, VB-CABLE or translated Speak delivery.

Both capture workers stopped, closed their native handles and cleared queued
PCM. All owned browser/helper processes and the local server stopped. No PCM
file was saved and no cloud inference was called. The installed 1.1.1 bridge
hash matched the source DLL used for this measurement.

The result, process tree, fixture source hash, cleanup flags and probe script
are retained at
`D:\CodexBuilds\Translito-quality\browser-child-constant-20261102`.
The earlier HTTP-controlled fixture failed before measurement and is retained
separately under `browser-child-20261102T1755Z`; it is not a passing capture
result. No production code or installer changed for this verification.

## Meeting menu references

Menu paths checked against primary help pages on 2026-11-02:
[Zoom](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0060836),
[Teams](https://support.microsoft.com/en-us/teams/notifications-settings/manage-your-device-settings-in-microsoft-teams),
[Slack](https://slack.com/help/articles/1500002037922-Adjust-your-huddles-preferences),
[Meet](https://support.google.com/meet/answer/10409699?hl=en-EN),
[Discord](https://support.discord.com/hc/en-us/articles/33030151293079-Discord-Voice-Video-Streaming-Guide).
The guide provides direct links; menu wording may vary by app version.
