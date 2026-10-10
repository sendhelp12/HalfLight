# Setup guide

## First installation

Install both owned games and Dying Light 2 Developer Tools. Close the games before installing the Half Sword loader. Run `Setup.cmd`, choose the installation folders and click **Check installations**, then **Install / Resume**.

Setup verifies exact supported builds and downloads checksum-pinned Python, UE4SS, Zig, MinHook, .NET, CUE4Parse, Blender and Capstone. It builds the authored bridge locally. Existing different loader files are preserved and reported as conflicts; other mods and their settings are preserved.

When asked, open each game once: a Half Sword match and a DL2 single-player save. Leave F8 off. Setup generates fresh reflection mappings, captures the 27 weapon assemblies and both source palms, restores the source equipment, extracts local meshes, exports and compiles them using your own Developer Tools, installs them into a separate owned asset directory, and calibrates against the loaded DL2 player's rig. It verifies every weapon instance and the live bridge before marking installation complete.

The setup editor may appear while compiling. Leave it alone until setup finishes; the installer closes its disposable editor afterward. No mouse or keyboard input is injected into gameplay.

## Daily use

Open both games into their playable sessions, then run `HalfLight.cmd`. F7 stays available for **Start Bridge**, **Stop Bridge**, **Restart Bridge**, weapon selection and component status. F8 enables control. Start and Restart deliberately begin with F8 off.

When native damage says it needs a normal melee hit, land one normal DL2 hit with F8 off. Use a native cutting weapon for the cutting-hit context. Enable F8 afterward. The status panel reports fresh source poses, rendering, camera sync, hand adapters, input filtering, equipping, cleanup and performance separately.

Half Sword rendering suppression is active while the bridge is connected. Stop Bridge restores rendering and the saved simulation settings.

## If setup stops

Read the stage and error shown in the setup window. Correct the prerequisite and click **Install / Resume**. Do not repeatedly restart the games unless the error specifically concerns installing a loader into an already running game. Unsupported builds and conflicting files require resolution before setup can continue.

Downloads and cooking outputs are verified before use. A failed live check leaves installation unready. The bridge refuses attachment when native callback restoration cannot be verified.

Private setup and runtime logs can contain installation paths and game-derived information. Do not post them publicly without redaction. Keep `.local/` until uninstall finishes because its journals record ownership and backups.

## Uninstall

Stop the bridge and close both games. Double-click `Uninstall.cmd`. It restores backed-up authored loader files and removes only unchanged loader/assets installed by this setup. Pre-existing matching loader files, other mods and user-modified files are preserved. A preservation warning means those files need manual review.

The source folder contains private tool downloads, extraction and cooking caches. These can be removed after successful uninstall. The disposable Developer Tools project is a local build cache and is not part of the public download.

## Alpha release checks

- [x] Fresh mapping, weapon capture, owned archive extraction and official mesh cooking.
- [x] Fresh anatomical calibration against the current campaign rig.
- [x] Live loading of all 54 weapon banks, both hand adapters and native equipping of all 27 weapons in both hands.
- [x] Bridge restart without restarting either game.
- [x] Ownership-aware loader and asset installation/uninstall with preservation tests.
- [x] Pinned tool downloads, authored native builds and installer/privacy regressions.
- [x] Source/index/history audit and regression tests in a separate source-only folder.
- [x] Visual gameplay check accepted by the user on 11 October 2026.
- [x] User approved v0.1.0-alpha.1 for public testing on 11 October 2026.

The following are community testing priorities, not blockers for this alpha:

- Extended crowded-combat, inventory/loading and death-recovery coverage.
- First installation on a separate clean Windows machine.

No repository has been uploaded. Public source commits must use the anonymous project identity required by `work/release_audit.py`; personal Git author/committer metadata is rejected.
