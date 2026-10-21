# Tactical AI rehearsal

The director divides enemy infantry by division into squads of up to six.
When the force is large enough, every fourth squad is held as a mobile reserve.
Initial squads hold separate capture sectors; other squads contest uncaptured
sectors and reserves respond to player presence. Tanks and reconnaissance
vehicles receive separate destinations. Anti-tank and anti-aircraft guns move
to support positions. Artillery, rocket launchers and self-propelled artillery
remain at their deployment positions with AI movement disabled and open fire
enabled; they can engage targets within native weapon range. No bombardment
range increase or guaranteed line of sight is implied. These rear guns receive
no capture-point waypoints. The changed rear behaviour needs a new live check;
the preceding rehearsal verified the earlier moving-artillery behaviour.
unarmed transport trucks remain parked and crew links remain intact.

Orders are evaluated every 15 seconds, but movement is issued only when the
assigned destination changes. A group with nobody at its destination receives
a renewed movement order every 60 seconds. Infantry arriving in its sector
uses the shipped `actor_to_cover` action once per assignment. This avoids the
old recurring movement/state reset that interrupted combat and cover.

`ai-plan.json` records group membership, roles and destinations in each generated
session. Casualty identities, manpower weights and parent/crew links are unchanged.

## Isolated game test

Exit the previous MoW mission and close the ordinary bridge worker. Run
`Start_Tactical_AI_Trial.cmd`. If the previous user-cancelled transition is still
recorded, the trial verifies that MoW has exited it, checks for a final result or
partial strategic return, and archives the unfinished transition. It refuses to
discard a completed result. The actual worker lock prevents concurrent transfer.

The trial builds a new UUID from the existing formation fixture. The player
controls Soviet infantry against German infantry, eight light tanks, a scout
vehicle and an artillery piece. Installation retains the usual file backups.
This test has no strategic result import path. After the preparation minute,
observe movement for two or three minutes and save as `HMB_ai_director_probe`.
Initial loading is verified using the native UUID/roster autosave. A loading PASS
does not verify gun pathfinding or cover behaviour; these need runtime inspection.

130 automated tests pass; the 115-actor fixture generates.

## Live verification, 2026-10-15

Battle `9217ccc839a74f559605552c8675b60b` loaded and was played to a player
victory, 100 points against 32. The player confirmed that infantry acted
effectively and all combat vehicle types moved, including the gun. The saved
state matches the fixture UUID. All 16 remaining enemy infantry entities were
more than 300 map units from their spawn positions; nine of ten remaining
grouped vehicle entities were also more than 300 units away. The artillery
piece displaced 1617.73 units. One infantry group records a cover order issued;
this proves execution of the branch, not that every actor found usable cover.
The player reports ambushing enemy tanks with an anti-tank gun. Reserve
responses remain unverified: this small force has only three infantry squads.

Evidence and archived native save:
`native_trial/evidence/tactical_ai_9217ccc839a74f559605552c8675b60b/probe/ai-behaviour-verification.json`.

The casualty discrepancy was resolved on the same archived save: AS2 counts
unburned knocked-out hulls as well as burned wrecks. The added strict signature
requires broken body and chassis, interaction flag `broken`, disabled selection,
no `Operatable`, and no hull repair timer. Engine/track damage alone still does
not qualify. The corrected audit exactly matches native totals: Germany 23 men
and seven vehicles, USSR 24 men and no vehicles. Removed crew and culled corpses
remain accepted only with matching native counts. Evidence:
`corrected-casualty-audit.json` beside the preceding report. No strategic results
were imported. 132 automated tests pass after both changes.
