# Third-party notices

Dependencies are obtained locally; their binaries and game content are not bundled in this source workspace. Preserve their upstream license notices in local tool installations. Versions not pinned below must be resolved before release.

| Project | Role | License/source |
| --- | --- | --- |
| [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) | Half Sword Lua loader/reflection | [MIT license](https://github.com/UE4SS-RE/RE-UE4SS/blob/main/LICENSE); pinned v3.0.1-1152-ge3ba1016, checksum in profiles/loader.json; downloaded privately with its license |
| [CUE4Parse](https://github.com/FabianFG/CUE4Parse) | Local Unreal asset reader | [Apache-2.0](https://github.com/FabianFG/CUE4Parse/blob/master/LICENSE); commit 52f96d60eadf95f2933a5599461d94f0774d08c1 |
| [MinHook](https://github.com/TsudaKageyu/minhook) | Native input hook | [BSD-2-Clause](https://github.com/TsudaKageyu/minhook/blob/master/LICENSE.txt); 1.3.4 |
| [Python](https://www.python.org/) | Companion runtime/installer | [PSF license](https://docs.python.org/3/license.html); embedded Windows x64 3.12.10 |
| [Zig](https://ziglang.org/) | Native mod compilation | [MIT and bundled-component notices](https://github.com/ziglang/zig/blob/master/LICENSE); 0.13.0 |
| [Blender](https://www.blender.org/) | Local mesh conversion | [GPL](https://www.blender.org/about/license/); 3.6.23 |
| [.NET](https://github.com/dotnet/runtime) | Local extractor build/runtime | [MIT and dependency notices](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT); SDK 10.0.401 |
| [Capstone](https://github.com/capstone-engine/capstone) | Installer/runtime verification against local binaries | [BSD](https://github.com/capstone-engine/capstone/blob/next/LICENSE.TXT); pinned 5.0.9, downloaded privately |
| [Lupa](https://github.com/scoder/lupa) | Lua regression tests | [MIT and Lua notices](https://github.com/scoder/lupa/blob/master/LICENSE.txt); development dependency 2.8 |
| [Dying Light 2 Developer Tools](https://store.steampowered.com/app/2217480/) | Player-owned exporter/compiler | Proprietary tooling; use the user's installation, do not redistribute |

The Techland exporter and any game-derived materials, mesh data, reflection mappings or native rig poses are excluded. The mod's license does not apply to those files.

Credits also include the [AI Game Modding Guides](https://github.com/trevaintdead/ai-game-modding-guides) for the source-only publishing workflow. AI assistance was provided by OpenAI Codex. No generated art or audio is included.

The earlier development investigation consulted [AESDumpster](https://github.com/GHFear/AESDumpster). The release's local scanner uses authored immediate-store decoding; no AESDumpster pattern tables or source are included or required.
