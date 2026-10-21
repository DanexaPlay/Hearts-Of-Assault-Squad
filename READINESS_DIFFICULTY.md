# Organisation and difficulty, 2026-10-15

## Organisation

Native automatic exports read each participating CArmy's current organisation
and cached maximum (`*(army+312)+640`, statId 60, fixed point 1e-5). This is a
read-only operation on the version-locked 1.19.3 runtime; no getter is called.
Campaign identity, paused game hour, exact unit IDs and saved current values
must match. Failure stops generation rather than substituting a guessed cap.
The snapshot is separate from saved division dictionaries, so strategic
snapshot comparisons remain valid.

The native maximum includes the game's cached active-unit statistics instead
of a universal 100-point or template-only assumption. Each battalion/support
component's normal infantry/vehicle count is multiplied by current/max org,
clamped to 0..1, and rounded up. Each positive component keeps at least one
representative. Vehicles retain complete native crews. Thus small formations
and very low organisation do not scale exactly proportionally; preserving
components and operational crews sets a floor. No division becomes empty.

When the actor budget is below the number of equipment variants, proportional
model allocation no longer forces extra actors to show every minority model.
The entire original manpower/equipment weight is still distributed over the
deployed actors. Fewer actors are readiness, not pre-applied strategic deaths.
Existing casualty caps and exact variant accounting remain in force.

Synthetic/old fixtures without a verified organisation snapshot retain their
previous full-count behaviour. The automatic native path sets
`organization_scaling_required`; a missing unit then raises an error.
Older manual non-native exports do not obtain the live cache automatically.

Read-only live evidence: `sessions/readiness-difficulty-proof/native-organization.json`.
GER `2:51`: 40.02216 / 53.45454 = 74.8714%; SOV `374:51`:
4.59 / 45.9 = 10%. Generated force: 61 actors, including intact gun crews and
one representative per positive component. The campaign was unchanged.

## Difficulty

The HOI4 save's top-level `difficulty` is exported with the battle:

| HOI4 | AS2 native rules |
| --- | --- |
| very_easy | easy |
| easy | easy |
| normal | normal |
| hard | hard |
| very_hard | heroic |

AS2 has four single-player profiles. The generated dedicated mod copies the
chosen shipped `.dl` profile into all four selectable profile filenames, along
with its native generic include. This enforces the desired battle coefficients
even when MoW retains another menu selection or the player loads manually.
The menu label may still display its previous selection. No approximation of
the native health, accuracy or armour multipliers is made.

Scope: these profile overrides affect all single-player missions while this
generated bridge mod is active. Disable the bridge mod for unrelated campaigns
that should use MoW's own difficulty selection. Settings in the user's profile
are never edited. Multiplayer's separate profile is not overwritten.

Changing profile resources forces the same verified-menu process restart used
for map changes, avoiding dependence on cached difficulty data. Identical rules
do not trigger another restart after acknowledgement. A persistent
`.hmb-engine-restart.json` receipt survives a failed shutdown and identical
reinstallation; it is cleared only after a newly launched process reaches its
own main page. Generated `difficulty.json` records the source,
mapped profile, exact file hash and pending engine verification.

## Verification

Automated coverage includes zero/half/full organisation, complete crews,
manpower/equipment conservation, low-count model allocation, stale native
snapshots, all five difficulty mappings, save parsing and restart detection.
Read-only organisation access and generation have been verified on the running
test campaign. 141 automated tests pass. Manual save `HMB_readiness_probe`
matches UUID `a69ec2b5f890442ba14331470dedd978`, all 61 actors, complete crews
and zero native casualties. Evidence is retained in that trial's
`probe/readiness-live-verification.json` and `manual-readiness-save`.

The first new-profile trial could not close the old game within 30 seconds.
An identical retry previously forgot that cache invalidation was outstanding;
the persistent receipt fixes this. The final trial
`tactical_ai_3e0874184b064e04b171f10e9abdcb06` launched `mowas_2.exe` directly as
PID 15352, verified a fresh engine main page and then acknowledged all 61 actors
from its native autosave. The receipt is cleared. Normal difficulty profile
resources were accepted after a confirmed cold launch. Other difficulty
mappings have automated resource tests; their combat multipliers have not been
independently measured in live battles.

`Start_Readiness_Difficulty_Trial.cmd` runs an isolated fixture made from that
verified snapshot, using the existing menu loader and UUID/roster acknowledgement.
It never imports results to HOI4. Save as `HMB_readiness_probe` after loading.
