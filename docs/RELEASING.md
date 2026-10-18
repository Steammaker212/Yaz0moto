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
`miyamoto/updater.py` looks at the releases of `GITHUB_REPO` (`Steammaker212/Yaz0moto`), picks the file whose
name ends with the right platform suffix, and expects the executable names `Yaz0moto.exe`, `Yaz0moto.app`
and `Yaz0moto.AppImage` inside. If you rename the repository or the program, change them together;
`tests/branding_test.py` fails when the updater, build scripts, desktop file and workflows disagree.

## Pulling in changes from Pyamoto
```
git remote add upstream https://github.com/Zenith-Team/Pyamoto.git   # once
git fetch upstream
git checkout -b sync-upstream deluxe-support
git merge upstream/master
```
Expect conflicts in lines that were renamed (strings, `pyamoto.py` -> `yaz0moto.py`, workflows). Resolve them
keeping the Yaz0moto names, run both tests, then open a pull request into `deluxe-support`. Keep upstream's licence
headers and credits as they are.

## Branding
App icons are in `miyamotodata/app_icons/` and the README banner is `docs/banner.png`.
