# Package evryBuild - POB for LocalExile

This guide builds the external SQLite edition and prepares a local Windows x64 portable ZIP.
The Linux AppImage is built by CI; see [Linux AppImage](#linux-appimage).
It does not publish a release, push Git changes or modify a LocalExile installation.
The earlier API-based ZIP is a different implementation; do not label it as the external exporter.

## Build requirements

Use Windows x64 with the .NET 10 SDK, PowerShell, Python 3.10+ and the
[LocalExile/evryBuild source checkout](https://github.com/LocalExile/evryBuild).
The checked-in planner runtime is reused; a separate PoB installation or LocalExile checkout is not needed to package it.
The exporter is self-contained, so users of the resulting ZIP do not need .NET or Python installed.

Open PowerShell in the evryBuild repository root (the folder containing `src`, `runtime`, `tools` and `manifest.xml`).
For example, if you cloned it to `C:\src\evryBuild`, first run:

```powershell
Set-Location 'C:\src\evryBuild'
```

Replace that example path with your actual checkout. Confirm the prerequisites:

```powershell
dotnet --version
python --version
$PSVersionTable.PSVersion
```

The SDK should report `10.x`, and Python should report `3.10` or newer.

## Build and validate

Run these commands from that same PowerShell window, stopping if any command fails:

```powershell
.\scripts\build-exporter.ps1
dotnet test tests/LocalExile.Export.Tests
python tests/evrybuild/test_localexile.py -v
python tests/evrybuild/test_exporter.py -v
python tests/evrybuild/test_updater.py -v
python -m unittest discover -s scripts -p test_package_evrybuild.py -v
```

The build writes `runtime/LocalExile/evryBuild.Export.exe` and a receipt containing its SHA-256 and source hashes.
Packaging refuses a missing, changed or stale exporter. Rebuild it after changing the exporter source or notices.
See [validation instructions](tests/evrybuild/README.md) for optional real-data checks and the native game result.
Without explicit real-data paths, that one optional test is skipped; all other checks must pass.

## Versions

evryBuild has its own [semantic version](https://semver.org/) in the `VERSION` file, separate from the upstream PoB
version in `manifest.xml` (the planner it is based on). The portable application shows it, and updates compare it.

| Change | Bump | Example |
|---|---|---|
| Fixes only | Patch | 1.2.0 to 1.2.1 |
| New features, compatible | Minor | 1.2.1 to 1.3.0 |
| Users must reinstall, or the save/export contract changes | Major | 1.3.0 to 2.0.0 |

A release candidate is `1.3.0-rc.1`, `1.3.0-rc.2`, and so on; it sorts before `1.3.0`. Publish candidates as GitHub
pre-releases so that only people who download them get them. The dated releases up to 2026.11.03 predate versioning
and the updater; 1.0.0 is the first versioned release.

## Prepare a release

A release package updates itself from later releases, so it is built from a clean commit that is pushed to
`LocalExile/evryBuild` before anyone can update from it. In one commit:

1. Set `VERSION` to the new version.
2. Head the newest `CHANGELOG.md` section `## <version> - <date>`, for example `## 1.2.0 - 2026-11-20`. Between
   releases it can say `## 1.2.0 - unreleased`, but packaging refuses that. The portable application shows this
   section when it offers the update.

Then, from the repository root with the exporter built and the tests passing:

```powershell
.\scripts\prepare-release.ps1
```

The tag is `evrybuild-v` and the version (`evrybuild-v1.2.0`); `-Tag` must match `VERSION` if you pass it. Plain
`v1.2.0` tags are not used: this fork carries upstream PoB's own tags, `v1.0.0` to `v2.67.2`, and GitHub attaches a
release to an existing tag instead of creating one. The script refuses uncommitted
changes, a tag that differs from `VERSION`, and a changelog heading that does not name the version. It copies every
file exactly as that commit stores it, and writes a new
`dist\release-<tag>-<time>` folder with the portable `evryBuild` folder and an `assets` folder holding:

| File | What it is |
|---|---|
| `evryBuild-Portable-Windows-x64.zip` and `.sha256` | The portable download for new users |
| `evryBuild-update.xml` | The update manifest: the commit, every file's source and SHA-256, and the release notes |
| `evryBuild.Export.exe` | The exporter, which is built rather than committed, so updates download it from the release |
| `evryBuild-package.json` | The package record, kept current by updates |

`evryBuild-package.json` records the source commit and the SHA-256 of each copied application file.
A package built without `-Tag` (with `scripts/package-evrybuild.py` alone) copies the working tree, including
uncommitted changes, and never updates itself; use it for local testing only.

## Publish and how updates find it

Push the commit, then create the release with the tag on that commit and attach every file in `assets`:

```powershell
gh release create evrybuild-v1.2.0 --repo LocalExile/evryBuild --target <commit> --title "evryBuild 1.2.0" --notes-file <notes.md> --latest (Get-ChildItem <assets folder>).FullName
```

For a release candidate, use `--prerelease` instead of `--latest`.

A portable copy checks `https://github.com/LocalExile/evryBuild/releases/latest/download/evryBuild-update.xml`
when it starts (Options: **Check for updates at startup**) and with **Check for Update**. It offers a release newer
than its own by semantic-version order. **Update Now** downloads only the files whose SHA-256 differs: committed files from
`raw.githubusercontent.com` at the release's commit, and the exporter and package record from the release. Every file
must match the manifest before anything changes. The update then renames each replaced file to `.old`, moves the
new one in, and restarts. It starts a new process when `evryBuild.exe` or a DLL changed. If any step fails, the
earlier steps are undone. `Builds/`, `Settings.xml`, `LocalExile.json` and other personal files are never touched.

Only the release GitHub marks **Latest** is offered. Publish as a pre-release first to test it with a separate copy;
nobody is offered it until it is marked Latest. Copies from the dated releases (up to 2026.11.03) have no updater
and need one manual download of 1.0.0 or later.

## Linux AppImage

`evryBuild-x86_64.AppImage` is the same application folder that `package-evrybuild.py` makes for the ZIP, plus Wine
11.0 to run it, an `AppRun` launcher, a desktop entry and an icon (`scripts/appimage/`). It is about 400 MB; most of it
is the planner's tree and game data, which the Windows ZIP holds too.

**Releases get it from CI, never from a local build.** The `Linux AppImage` workflow
(`.github/workflows/appimage.yml`) builds it on every pull request and push to `master` as a workflow artifact. When
an `evrybuild-v*` release is published, it builds the AppImage from that tag, as a release package (with `--release-tag`), and
attaches `evryBuild-x86_64.AppImage` and its `.sha256` to the release next to the Windows ZIP. Publish the release with
the other assets as above; the workflow adds the AppImage a few minutes later.

To build one locally for testing, on Linux x86_64 with the .NET 10 SDK, PowerShell and Python 3.10+:

```bash
pwsh scripts/build-exporter.ps1
mkdir -p dist
python3 scripts/package-appimage.py --output dist/evryBuild-x86_64.AppImage
```

The script downloads Wine ([Kron4ek's unpatched Wine 11.0 build](https://github.com/Kron4ek/Wine-Builds/releases/tag/11.0)),
appimagetool 1.9.1 and the AppImage runtime once into `dist/appimage-cache`, and uses each only if its SHA-256 matches
the pin in the script. To move to another Wine, change `WINE` and `WINE_ROOT` in `scripts/package-appimage.py` and the
version and source links in `scripts/appimage/notices/NOTICE-Wine.md` together; the packaging tests check that they
agree. The AppImage leaves out Wine's development files and 32-bit Windows libraries (evryBuild is 64-bit).

How the AppImage runs:

- `AppRun` starts `evryBuild.exe` with the bundled Wine, in its own prefix,
  `~/.local/share/evryBuild/appimage-prefix` (`$EVRYBUILD_WINEPREFIX` overrides it). It is kept apart from a prefix that
  another Wine uses, since two Wine versions cannot share a running prefix.
- The planner sees `EVRYBUILD_APPIMAGE` and keeps builds, settings and `LocalExile.json` in Wine's Documents folder
  (`~/Documents/evryBuild`), because the application folder is a read-only mount.
- The exporter is the Windows `evryBuild.Export.exe`, run by Wine like the planner. Database and data paths reach it as
  `Z:\...` paths, which Wine maps to `/...`. A native Linux exporter is not used: Wine starts a Linux program but does
  not connect the pipes the planner talks to the exporter through.
- A release AppImage checks for newer releases like the ZIP, but never updates itself: **Update Available** shows the
  notes and copies the release link, and the user replaces the AppImage. Nothing is written into the image.

Run the AppImage once on Linux before sharing a release, and use **Export to LocalExile → Preview** against a test
database to check that the exporter starts under Wine.

## Check the extracted package

Extract the ZIP to a new writable folder, open its `evryBuild` folder and run `evryBuild.exe`.
Confirm **Import/Export Build → Export to LocalExile** shows **Save database** and **Game data folder**,
with no URL or token fields. `README.md` and `docs/LocalExile.md` must be present in the extracted package.
Follow [the setup guide](docs/LocalExile.md) against a separate test database before distributing a newly changed converter.
The recorded native acceptance verifies a level-99 Witch on unmodified LocalExile `b2737133`; later converter changes
need their own appropriate regression checks.

Before sharing an artifact, confirm that `Builds/` is empty and there is no `Settings.xml` or `LocalExile.json`.
Use the SHA-256 file to identify the ZIP you validated. Publication is a separate owner action.

## Updating planner game data

Planner data maintenance still follows the relevant GGPK export and tree instructions in [CONTRIBUTING.md](CONTRIBUTING.md).
This does not change the LocalExile native save contract automatically. Keep conversion and compatibility rules tied to
verified server/client revisions, and mark unverified mechanics unknown rather than inferring support from a table entry.
