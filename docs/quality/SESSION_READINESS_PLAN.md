# Session readiness and settings implementation

The desktop uses one session plan for the active Listen or Speak language pair.
The preferred route is retained separately from the route actually running.
Explicit per-stage recognition choices win over automatic Free-mode selection.
Cloud setup is requested only when a required connection is missing or rejected;
model preparation and temporary recovery are presented as setup progress.

## Download behavior, including language changes

- On first launch, prepare Whisper Base and Lite translation for the current
  pair. Reuse compatible cached speech and quality translation models; honor
  pair-specific speech overrides and an explicit Lite selection. Larger models
  and models requiring license acceptance remain explicit downloads.
- For cloud, prepare the small local speech filter first. Native cloud translation
  can start without Lite; Lite is a lower priority local backup.
- Recompute required files when the user changes either language, switches
  Listen/Speak, changes an engine override, or changes network policy.
- Share files across pairs. Deduplicate by repository, retain partial files, and
  pause obsolete automatic jobs. Prioritize the new pair's required resources
  ahead of backup resources, including required files previously queued manually.
  Active manual downloads keep their user intent.
- Pause a lower priority automatic transfer when a required resource takes
  precedence. Returning to an earlier pair resumes an automatically superseded
  transfer from its partial files.
- Show the current file, state, percentage and progress bar in the main window;
  provide Pause/Resume and Cancel there, in Models, and through the tray.
  Models also shows downloaded bytes, total, speed and estimated time.
- A user's Pause or Cancel persists across refreshes, pair switches and restart.
  Resume is explicit. Cancel stops the transfer and retains partial files;
  removing downloaded files is a separate Models action.
- Language and engine edits during capture apply to the next session. The
  running route retains its original snapshot while the new pair can prepare.
- Internet blocking stops active/background transfers immediately. Automatic
  setup may resume after unblocking, but manually paused/cancelled work does not.

## Other acceptance criteria

Validated pending money edits commit on debounce, Enter, blur or Start. Partial
or invalid text never changes the live spending cap. Presentation and valid
budget edits apply live; source, engine and language changes apply next session.
Recovered transports retain the latest global/provider caps and fallback policy.
Stop invalidates pending startup callbacks. Scheduled capture owns only its
own session and becomes active only after capture starts. Model notifications
open Models or dismiss; they cannot stop a meeting. Disconnected saved devices
require selection rather than silently capturing another device. Replies off
cancels pending output. Transcript save failures preserve the transcript.

Verification covers route combinations, required versus backup downloads,
rapid language changes, partial-file reuse, sticky Pause/Cancel, restart,
network blocking, stale startup callbacks, scheduler ownership, and native
dark UI at the existing window dimensions. Release checks precede publishing
Windows builds and updating landing-page download links.
