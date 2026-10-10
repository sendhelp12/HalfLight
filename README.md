# HalfLight

An experimental Windows single-player bridge that brings Half Sword weapon motion into Dying Light 2.

**v0.1.0-alpha.1 — first public alpha, approved for community testing.** Clean-machine installation and extended combat/recovery coverage are community testing priorities; they do not block this alpha release.

Setup builds the mod and prepares weapons from your own installed games. No game models, textures, archives, executable files, captured rig data or archive keys are distributed.

## Requirements

- Windows x64 and your own installed copies of Half Sword and Dying Light 2.
- The matching free [Dying Light 2 Developer Tools](https://store.steampowered.com/app/2217480/), installed under Dying Light 2's `DevTools` folder.
- Internet access for verified third-party tools, plus space for their downloads and local build outputs.
- Exact supported game/module identities listed in [profiles/retail.json](profiles/retail.json). Setup refuses other builds. The verified Developer Tools identity is `DevTools_DyingLight2_20260825_094519_6422187`.

Use offline single-player. Back up your saves before using this experimental mod.

## Installation

1. Extract the source repository into a writable folder. Keep the folder there after installation.
2. Close both games and double-click **Setup.cmd**.
3. Select the game installations, click **Check installations**, then **Install / Resume**.
4. When setup asks, open Half Sword into a match and DL2 into a single-player save. Leave F8 off. Keep both games and the setup window open while setup captures, extracts, cooks and calibrates locally.
5. Wait for the installation success message. Launch **HalfLight.cmd** for later sessions. **F7** opens weapons, bridge controls and status; **F8** enables weapon control.

Each game needs to open once during first setup. Installed assets are refreshed in the running DL2 session. You do not need repeated game relaunches between setup stages. The first build can take several minutes; the setup window reports its current stage.

See [SETUP.md](SETUP.md) for troubleshooting, uninstall and verification limits.

## Weapons and controls

The catalogue contains 27 distinct weapon builds across swords, daggers, axes, hafted weapons, maces, polearms and staves. Filter by type and equip each hand independently in F7, including duplicate or mixed pairs. Native Half Sword hand and grip restrictions apply.

| Control | Action |
| --- | --- |
| F7 | Weapon menu, Start, Stop, Restart and component status |
| F8 | Toggle bridge control; Start/Restart begins with it off |
| Left mouse | Main/right weapon control |
| Right mouse | Other/left weapon control; toggle supported two-hand grip |
| Alt | Alternate swing/thrust modifier |
| X | Swap weapon hands |

Normal DL2 attack/block is filtered while F8 is active. Half Sword world rendering and unnecessary enemy simulation are suppressed while connected, and dropped weapons are cleaned up. Stop Bridge restores the source settings. Smoothing, native CUT/BLUNT impact profiles and host-only weapon sticking are included. Campaign scenery collision is excluded.

After a fresh campaign attachment, make one normal DL2 melee hit with F8 off to provide the current player's native damage context. F7 shows when native damage is ready. A cutting weapon supplies the blade-hit context for cutting effects.

## Verification status

The local source installation has completed fresh weapon extraction, official cooking of 54 hand-specific weapon banks, calibration of 108 hand templates and live attachment. Start/Stop/Restart and automatic rebinding after a player/rig change have been checked without relaunching either game. Installer/privacy regressions pass in a separate source-only folder, and native hand/smoothing fixtures pass.

The user accepted the visual gameplay check on 11 October 2026. Live damage, native weapon equipping, rendering suppression and bridge recovery checks have passed locally. Extended crowded-combat and death-recovery coverage has not been independently established, and installation on a separate clean Windows machine remains unverified. See [SETUP.md](SETUP.md) for verification limits.

## Content, privacy and credits

Generated assets, installation paths, archive keys, calibration, mappings and logs stay in ignored private folders. Never upload `.local/`, runtime folders or game-derived output. Before sharing source, run `python -m unittest discover -s tests` and `python work/release_audit.py --tracked` against the final Git index.

Unofficial fan project, not affiliated with or endorsed by Half Sword's developers or Techland. Game content remains the property of its owners. Original mod code uses the [MIT license](LICENSE); that grants no rights to game content or third-party tools.

Built with OpenAI Codex and AI coding assistance. Dependency credits are in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Prepared using the [AI Game Modding Guides publishing checklist](https://github.com/trevaintdead/ai-game-modding-guides/blob/main/guides/10-posting-your-project.md).

## Alpha feedback

Report whether this was a first installation or an existing setup, which weapon/hand combination you used, what you expected and what happened. Useful testing includes first-time setup, crowded fights, inventory/loading transitions and death/respawn recovery. Do not upload extracted assets, archive keys, calibration, raw private logs or your `.local/` folder.
