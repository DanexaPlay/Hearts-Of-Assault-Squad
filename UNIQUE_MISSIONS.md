# Map loading without restarting MoW: experiment

## Latest verified status — 2026-10-16

STRATEGIC END-TO-END CONFIRMED: session `00ab548497e34d0f92de1977c14980d3`,
battle `dfa84177001b40da81ae4d1f3300c617`, selected combat 6:62, province 9203.
The main bridge reused the running MoW, automatically navigated the seven-slot
menu, dismissed the loading prompt, and verified all 61 actors on frozen_river.
No engine restart was requested; all 15 terrain files were physically skipped.
The tactical winner was attacker. Native strategic return is verified and
strategic_result_applied=true; no save/load was used for return. The user
confirmed the entire cycle worked. Evidence:
`sessions/automatic/00ab548497e34d0f92de1977c14980d3/map-bank-cycle-verification.json`.
Runtime acceptance now records strategic_end_to_end_with_bank_verified=true.
The completed session remains guarded until normal scene-exit handling sees
MoW's menu; no active pointer or game state was modified during this audit.
Statements about pending strategic validation below are earlier history.

FINAL UPDATE FOR THE MAP LOADER: automatic seven-map trial
`unique_maps_d584aba345d74e338e1d0c46fc1518f2` PASSED in PID 2640, with all
seven UUIDs/rosters, native static-map checks and the last terminal result.
All seven saved previews were reviewed: snow remains on the winter maps,
grass/fields on summer maps; the user reported no visible problems. This
does not constitute an exhaustive audit of all spawn sites. The trial record
now marks its visual check passed, rather than leaving it pending.

The main config now enables preinstalled_map_slots. Acceptance and exact
trial/catalogue hashes are recorded separately in runtime/map-bank-acceptance.json,
leaving the installed bank marker's startup timestamp unchanged. Main-config
preflight `main_bank_preflight_65ce6659022347d391d1ab3a9c8e522b` generated the
registered frozen-river slot with identical immutable geometry and difficulty
rules. Warm installation now SKIPS all immutable terrain files after checking
their hashes. The complete strategic cycle with this loader is still pending;
the isolated trial did not import any results into HOI4. 155 tests pass.

Shared difficulty changes and newly added/changed custom infantry breeds still
request a cold engine; identical shared resources do not. Restore_Regular_Missions.cmd
also disables the bank config when restoring the legacy mission. The setup
manifest retains its original preparation-time status; runtime acceptance above
records subsequent verification. Earlier status paragraphs below are history.

Update after the seven-map setup: the user successfully ran preparation
`map_bank_cca0f08f71594b87bb28bef902f1599f`. Computer Use confirmed exactly seven
buttons (winter_hills, argentan, winter_fields, winter_town, spring,
frozen_river, road), with no old experiment entries. The bundled reference
and all seven coordinates now match that clean menu. Calibration evidence
is archived in that preparation's `menu-calibration/verification.json`.
The old six-entry calibration is superseded. Start_Map_Bank_Trial.cmd is the
user-run automatic seven-map warm-loader rehearsal; its result is pending.
The unit test also verifies that a running-game launch receives the selected
slot and the entire registered catalogue, and rejects stale menu catalogues.

The preinstalled full-map slots passed a live three-map test in the SAME MoW
process, PID 25484. Evidence:
`native_trial/evidence/map_bank_live_10260ecc24514b3182591961452ffafa/verification.json`.
Sequence: frozen_river → road → spring; 61/61/61 actors; matching all
2731/1007/10113 static entities and native bounds. All final results were read
without importing anything into HOI4. Archived live screenshots show actual
snow on frozen_river and grass/fields with distinct relief on road and spring.
This is not an exhaustive audit of every spawn position or terrain collision.

The live actions used Computer Use. The automatic bank-menu route is
implemented but has NOT yet passed an end-to-end live test. AS2 discovers old
folders even without interface.set; the pilot still has six menu entries,
including three obsolete folders. Its six-entry menu was calibrated.

Prepare_Map_Bank.cmd now prepares all SEVEN configured multiplayer maps,
archives whole obsolete battle/resources directories outside the mod, and
starts MoW from its proper working directory. It requires the game/editor
closed and no active strategic transition. Seven-map generation preflight
passed in `full_bank_preflight_9d24ec67749d4c849ff4441066cb774b` without changing
the installed pilot. The clean seven-entry menu needs fresh calibration after
setup; the old six-entry screenshot must not be treated as its proof.

The ordinary bridge is blocked while this experimental bank is installed,
preventing its fixed first-button route from opening the wrong map.
Restore_Regular_Missions.cmd (game closed) archives the bank folders and
restores the known-good full legacy mission. Production config is unchanged.

Next: install the seven-map bank, calibrate the clean menu, verify the automatic
warm loader, then enable it in the strategic bridge. Gazala is excluded because
it lacks native capture anchors and needs separate mission validation.

The sections below retain earlier research history. Failed include/Land
routes are not production features.

## Runtime findings and current approach

The whole-mission namespace implementation below is behind the experimental
`unique_mission_paths` flag and is NOT the default generator. Live trial
`unique_maps_95f8eeae8402484ca617c9b597538f9b` selected the previous fixed-path
mission despite new files on disk; the UUID guard refused its acknowledgement.
A second approach used the fixed menu entry and an SDL include of a newly
created map resource folder. Trial `unique_maps_39283fb64d934e16ac43d6fe819237be`
failed with file-not-found for `resources_9f6c07a6b8af45e2995c8fd836a479ac/map`
even though the installed file exists. This indicates that new mod files are
not reliably registered by an already-running resource repository, beyond
merely a stale menu selection.

The current `linked_map_resources` experiment therefore retains
`single/hmb/battle` and writes its map descriptor as an SDL include of the
selected ORIGINAL `/map/multi/.../map` or `/map/single/.../map` from map.pak.
Those immutable resources are already registered at startup. Native map copies
are retained as source evidence outside the installed mod, rather than replacing
the fixed path's old geometry. A validated `hmb-map-link.json` records the exact
descriptor hash and native namespace. Difficulty changes still require restart.

Native archive include trial `unique_maps_49a3b3f4b5e4456f959cac1af39ee3a2`
kept PID 10360 across all three maps and verified all 61 actors each time,
2731/1007/10113 static entities respectively, matching pathing bounds and the
last terminal result. However, visual inspection of archived `preview.jpg`
files showed snow on the two grass/field maps. Their original materials and
native previews confirm that the snow is incorrect. Thus the include changed
map objects and clipping, but did not bind the land resources to the included
map's namespace. The trial's former loader PASS is explicitly marked as a
terrain verification failure. This route is NOT enabled in production.

The current trial now embeds the shipped `service/land/land` definition's
Skeleton/VolumeView and land/grass extenders into the map's Land block, changing
only their three resource references to absolute native `.ply`, `.net` and
`.grs` paths. The existing native source mesh/materials themselves remain
unchanged. The installer validates all three bindings and the descriptor hash.
This Land-state override FAILED in trial unique_maps_d1ae70559d4e4451b8dd3bc78bdb183f: snow persisted, actors appeared below hills, and the third map crashed in VolumeView. It must not be enabled in production.

The original generator remains the production default until this terrain
visual check passes. Do not infer full map correctness from the roster and
static-map proof alone.

## Whole-mission namespace implementation (experimental)

New generation assigns `mission_path = single/hmb/battle_<battle UUID>`.
The map, heightmap, ground mesh, materials, mission and localisation all use
that namespace. The original shipped map content remains unchanged. A second
battle never replaces geometry at the first battle's virtual path.

The installer discovers exactly one generated mission, records its relative
filename and verifies the installed mission hash before loading. Reinstalling
different bytes into an existing UUID namespace is refused. A corrected or new
encounter needs a new battle UUID. Launcher and reopening rehearsal no longer
assume the old fixed `single/hmb/battle/0.mi` path.

On installing a new unique mission, only previous generated `interface.set`
discovery files are hidden from the campaign menu. Geometry and mission data
are retained for saved-game references. Hidden discovery files are backed up
alongside replaced shared metadata, and an installation failure rolls back
both writes and removals. The existing single active strategic transition
guard and worker lock remain in force.

Result parsing binds the exact virtual mission path plus the UUID in its outro.
An outro from the old fixed path is insufficient evidence for a new-path
battle even if it happens to contain the same UUID. Sessions created before
this change omit `mission_path` and continue using the legacy path, including
their existing retry and result import behaviour.

New unique geometry does not request a process restart. Changes under the old
fixed map path still do; shared difficulty profile changes and outstanding
cache-reset receipts still require a fresh process. Per-battle files are kept
because deleting them immediately could invalidate a saved mission. No automatic
deletion of old resources is introduced here.

## Verification

148 automated tests pass, including immutable path collisions, old-resource
preservation, menu-only hiding with rollback, exact progress-path binding and
legacy result compatibility. Preflight generated all 61 actors on existing
`multi/1v1_frozen_river`, `multi/1v1_road` and `multi/1v1_spring` maps.

The user-run `Start_Unique_Maps_Trial.cmd` tests the native-archive link on these three maps in order,
requiring return to the main menu between them. It checks that MoW keeps the
same PID and uses the warm loader, and verifies each UUID and complete roster
from native autosaves. The last battle has five seconds preparation and a
30-second timer, allowing a terminal result check using the unique progress
path. This isolated rehearsal never imports losses into HOI4. Runtime proof
is still pending; generated files alone do not establish that the engine's
mission catalogue refreshes while it remains open.

## Preinstalled complete map bank (current experiment, 2026-10-16)

The failed fixed-path descriptor was restored from the last verified full native mission. Three complete source maps (frozen_river, road, spring) are now installed before engine startup under stable, source-map-bound SHA256 namespaces. Mesh, heightmap, grass, materials, scene and supporting files retain their original bytes and relative names. No include or Land override is used.

Prepare_Map_Bank.cmd requires MoW and its editor closed, no active strategic transition, and the worker lock. It generates all packages before installation. The persisted catalogue hashes each immutable resource. Subsequent payload installation refuses unknown slots or changed terrain before writes, preserves other map menu entries, and binds result detection to the selected slot plus battle UUID. The main bridge still uses its proven legacy route: the bank is NOT enabled in production.

The first bank deliberately covers the three maps that reproduced the defect. The campaign Gazala map lacks native capture markers and was not added; ordinary generation currently rejects that map with Invalid AI point count. It needs separate spawn/objective validation before expansion of this bank.

Next live checks: calibrate the three registered menu buttons, warm-load river then road then spring in one process, inspect terrain screenshots and heights, and verify the final tactical result. A roster/static-entity PASS alone is insufficient.
