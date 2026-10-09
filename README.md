# Quake II — Custom Balance Mod (ammo + weapon damage + armor)

**Status: validated source patcher and GitHub Actions build recipe; no compiled DLL is included.**

This modifies the game logic in the [official Quake II 2023 remaster SDK](https://github.com/id-Software/quake2-rerelease-dll). The patcher also supports [original/classic Quake II](https://github.com/id-Software/Quake-2), but the automated build workflow targets the **2023 remaster** only.

## Gameplay changes

| Ammo | Initial limit | Bandolier limit | Ammo Pack limit |
|---|---:|---:|---:|
| Bullets | 500 | 750 | 1,000 |
| Shells | 200 | 200 | 200 |
| Rockets | 100 | 100 (unchanged) | 200 |
| Grenades | 100 | 100 (unchanged) | 200 |
| Cells | 500 | 750 | 1,000 |
| Slugs | 100 | 150 | 200 |

- Shotgun, Super Shotgun, Machinegun, Chaingun: **+20% damage**.
- Blaster and HyperBlaster: **+50% damage**.
- Jacket Armor: **50** instead of 25.
- Combat Armor: **100** instead of 50.
- Body Armor: **200** instead of 100.
- Armor shards: **5** instead of 2.
- Armor protection types and armor maximums (Jacket 50, Combat 100, Body 200) are unchanged. Armor conversion/salvaging works with the increased pickup quantities.
- Weapon damage uses unbiased random rounding to preserve the exact requested damage multiplier on average. Fire rate, ammunition consumption, weapon knockback, pellet count, and enemy damage are unchanged.
- Expansion-only ammo types remain stock.

The game uses integer damage, hence +20% for a 4-damage shotgun pellet averages 4.8 via random rounding, not a constant rounded 5.

## Steam Deck / Proton: build without Visual Studio on the Deck

The remaster distributed by Steam is a **Windows game running through Proton**. It needs a Windows `game_x64.dll`, NOT a native-Linux `game.so` file.

This package contains `.github/workflows/build.yml`, a **GitHub Actions build workflow**. It automatically downloads id Software's SDK and builds a Windows x64 DLL on a temporary GitHub-hosted Windows runner. You do **not** need Visual Studio on your Steam Deck.

1. Create a GitHub repository under your own account (a **private** repo is fine).
2. Add `patch_quake2.py` at the repository root and `.github/workflows/build.yml` at that exact path. (Upload or commit these extracted files; do not only upload the ZIP without extracting it.) The tests are optional for this build.
3. In the repository's **Actions** tab, choose **Build Quake II balance DLL**, then **Run workflow**.
4. After the action completes successfully, download the `quake2-balance-remaster-win64` build artifact. Extract it to get **`game_x64.dll`**.
5. In Steam Deck **Desktop Mode**, place `game_x64.dll` in a new `balance` directory under the remaster's writable user-data directory in its Proton prefix. The expected Windows location is `%USERPROFILE%/Saved Games/Nightdive Studios/Quake II/balance/`. The corresponding Linux path is inside Steam's `compatdata/2320/pfx/drive_c/users/steamuser/` directory, though installation paths can vary with the Steam library and Proton version.
6. In Steam, Quake II → Properties → Launch Options, add: `+set game balance`.
7. Start a **new** game and verify armor pickup values and maximum ammo. Old save files can retain the old limit fields.

If the writable Saved Games location is different on your system, locate the game's existing `%USERPROFILE%/Saved Games/Nightdive Studios/Quake II` folder in the Proton prefix. A separate mod folder is preferable to overwriting the base-game DLL.

**Note:** This GitHub workflow is provided but has *not been executed* here. SDK updates or dependency changes can require adjustments. If the build fails, download the job log and inspect the error before installing anything.

## Manual source patching

1. Download the official game SDK and extract it.
2. Run:

   ```bash
   python3 patch_quake2.py /path/to/quake2-rerelease-dll --edition remaster
   ```

3. Build the game DLL with a Windows-compatible toolchain as described in the SDK documentation.

You can also preview all changes with `--dry-run`. The patcher automatically makes `*.balance-original.bak` backups of the three edited source files (`p_client`, `g_items`, and `p_weapon`). Apply only to **pristine official source**; it refuses already-patched files.

To patch a classic Quake II source checkout, use `--edition classic`. The 2023 DLL is not compatible with classic-engine mods and vice versa.

## Tests and limits

From this directory, run `python3 -m unittest -q test_patch_quake2.py`. These are source-level regression tests, **not** a full game-DLL compilation or gameplay test. The patcher is designed for the referenced official SDK layouts. If an SDK revision changes, patching fails instead of making unchecked changes.