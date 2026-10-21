# Direct MoW mission loading: assessment, 2026-10-15

## Scope and evidence

Read-only examination of installed AS2 3.262.1 binaries and shipped resources,
the previous startup-template experiment, and public documentation search.
No DLL was injected, no executable was patched, and no internal function was
called in the running game during this assessment. The existing menu loader
remains the working implementation.

The installed x86 executable has no PE export directory. It contains
`mission.load %1%`, `gui.cmd.exec`, an active-template `exec` description,
`initialize.at` and `startup.at`. These are investigation leads, not a verified
external command protocol or callable function signature. Static scans found
no ordinary absolute references for the inspected strings; this does not prove
that the corresponding mechanisms are unused or inaccessible. Signature and
thread-safety work is still required. The UI archive's mission/briefing resources
are primarily graphics; it does not expose their loading callback as an editable
JavaScript loader. Shipped Lua scripts found in gamelogic.pak are multiplayer bot
scripts, not a demonstrated always-running main-menu request listener.

The earlier mod-local `/at/startup.at` experiment failed to start a mission and
was removed. It does not rule out a correctly timed engine command route, but
that route cannot currently be presented as working. Public search did not
identify a supported AS2 external mission-load API. Absence of a search result
is not proof that no such API exists.

Static observations and executable hash are retained in
`native_trial/evidence/mow_direct_load_research/static-strings.json` and
`pe-loader-candidates.json`.

## Candidate approaches

1. Verify an engine startup/command route. This is the cheapest experiment:
   establish that a harmless command is accepted, when mods are mounted, and
   whether it can enqueue a regular-game mission with difficulty and campaign
   context. A launch-only command would still require reopening MoW for each
   battle and would not solve reuse of an already-running game. No usable
   parameter is confirmed at present.
2. A small native x86 MoW extension receiving bridge requests and enqueuing the
   same internal operation used by the regular single-player mission launcher.
   This is the strongest candidate for running-game reuse without menu clicks.
   It requires identifying the loader and its context, submitting work on the
   correct engine thread, and recognizing briefing, running mission, completion
   and exit states. The existing UUID/roster autosave can remain independent
   proof that the requested battle actually loaded.

The extension must also handle different map resources without stale cached
geometry (a real crash was already observed on map replacement), difficulty,
profile/campaign initialization, cancellation, duplicate requests and process
exit. A single successful loader call is not sufficient evidence for a stable
replacement. Loading while minimized or without foreground focus is a separate
test: the engine may throttle or suspend progress. A bridge/background component
is still necessary; what can be removed is visible menu and key automation.

## Effort estimate, conditional rather than a delivery promise

- First bounded feasibility experiment: about 4–8 focused engineering hours.
  Goal: prove a command route or locate the real loading callback and context.
- If an accessible callback is established, an isolated native loading prototype
  is roughly another 1–3 working days.
- Repeated battle cycles, exit/cancel/restart handling, changed-map loading and
  regression checks can bring a reliable integration to roughly 1–2 working
  weeks in total. This estimate includes prototype work; it is not additional
  to it. If the internal entry points or lifecycle cannot be established, the
  estimate must be revised and feasibility remains open.

These estimates are engineering judgement based on the evidence above, not
claims from a source or guaranteed unattended agent completion times. Start
with the bounded experiment rather than committing to the whole extension.
