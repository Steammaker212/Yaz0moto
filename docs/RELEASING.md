# Maintainer guide

Notes for whoever maintains Yaz0moto.

## Branches
- `deluxe-support` is the default and only long-lived branch. Development, nightly builds and releases all come from it.
- Pull requests run the **Tests** workflow (`tests/deluxe_smoke_test.py` and `tests/branding_test.py`).

## Cutting a release
1. Add a new section at the top of `CHANGELOG.md` (`# Yaz0moto vX.Y.Z`).
2. Make sure the **Tests** workflow is green on `deluxe-support`.
3. Tag and push:
   ```
   git tag v1.0.1
   git push origin v1.0.1
   ```
   The **Release Build** workflow builds Windows, macOS and Linux and publishes a release named `v1.0.1`
   with the files `Yaz0moto-v1.0.1-Windows-x64.zip`, `-macOS-universal.zip`, `-Linux-x86_64.AppImage`
   and `-Linux-x86_64.zip`. Paste the changelog section into the release notes afterwards.
   (You can also run it by hand from the Actions tab and type the version.)

Version rules:
- Tags look like `v<major>.<minor>.<patch>`. The built-in updater compares them numerically, so each
  release must be higher than the last (`v1.0.1` < `v1.1.0` < `v2.0.0`).
- The version inside the build comes from the tag; `project.json` only matters when running from source.
- Never reuse the tags `v1.0`, `v1.0.1` or `v1.2` that came with the fork from Pyamoto.

## Nightly builds
Pushes to `deluxe-support` that touch code or data publish a pre-release named `nightly-<date>-<sha>`. Users who
choose the nightly update channel in Preferences receive these.

## What the updater checks
Updates are installed by the updater program, `yaz0moto_updater.py`, which `build.py` freezes on its own
(`build_updater.py`) into the package's `updater` folder (`Yaz0moto.app/Contents/Resources/updater` on macOS).
Yaz0moto imports the same file for the rules: it looks at the releases of `GITHUB_REPO`
(`Steammaker212/Yaz0moto`), picks the file whose name ends with the right platform suffix (the one named after
the release's version if there are several), and expects the executable names `Yaz0moto.exe`, `Yaz0moto.app`
and `Yaz0moto.AppImage` inside. If you rename the repository or the program, change them together;
`tests/branding_test.py` fails when the updater, build scripts, desktop file and workflows disagree, and
`tests/updater_test.py` checks downloading, installing, keeping user files and rolling back.

The build workflow runs `Yaz0moto-Updater version` on every platform: a package without a working updater
can't update itself. A release should contain a build of its own version (not a nightly renamed), although
the updater remembers the release it installed so it is not offered again.

## macOS signing and notarization
Without an Apple Developer account the macOS app is ad-hoc signed: it runs, but the first time someone opens a
downloaded copy macOS says it can't verify it, and they have to allow it once in **System Settings > Privacy &
Security > Open Anyway** (the release notes and README say how). Updates installed by Yaz0moto's updater don't ask.

To have Apple notarize it, so it opens with no warning, join the Apple Developer Program, create a
**Developer ID Application** certificate, and add these repository secrets (Settings > Secrets and variables >
Actions). The macOS build signs with the hardened runtime, notarizes, staples the ticket and checks Gatekeeper
accepts the app whenever `MACOS_CERTIFICATE` and `APPLE_ID` are set:

| Secret | What |
|---|---|
| `MACOS_CERTIFICATE` | the Developer ID Application certificate and its private key exported as a `.p12`, base64-encoded (`base64 -i cert.p12 \| pbcopy`) |
| `MACOS_CERTIFICATE_PASSWORD` | the password given when exporting the `.p12` |
| `APPLE_ID` | the Apple ID of the developer account |
| `APPLE_TEAM_ID` | the 10-character team ID (Membership details) |
| `APPLE_APP_PASSWORD` | an app-specific password for that Apple ID (account.apple.com > Sign-In and Security) |

The hardened runtime exceptions the frozen app needs are in `buildtools/macos-entitlements.plist`.

## Pulling in changes from Pyamoto
```
git remote add upstream https://github.com/Zenith-Team/Pyamoto.git   # once
git fetch upstream
git checkout -b sync-upstream deluxe-support
git merge upstream/master
```
Expect conflicts in lines that were renamed (strings, `pyamoto.py` -> `main.py`, workflows). Resolve them
keeping the Yaz0moto names, run both tests, then open a pull request into `deluxe-support`. Keep upstream's licence
headers and credits as they are.

## Branding
App icons are in `yaz0data/app_icons/` and the README banner is `docs/banner.png`.
