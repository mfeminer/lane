"""Write the three winget manifests for a published release.

winget wants a *multi-file* manifest: a version file that names the package, a locale
file carrying everything a human reads, and an installer file pinning the asset and its
`sha256`. They are generated rather than edited because two of the three fields that
change per release are a URL and a hash, and a hand-copied hash is only ever wrong
later — the same reasoning that keeps lane's own version in the git tag and nowhere
else.

Run through `make winget VERSION=0.2.0`. The release must already be published: the
hash is taken from the asset that users will actually download, not from a local build,
so a manifest can never describe a binary nobody has.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

PACKAGE = "mfeminer.lane"
REPO = "mfeminer/lane"
ASSET = "lane-windows-x86_64.exe"

# winget's schema version. Pinned rather than floating, because the validation that
# runs on a winget-pkgs pull request checks the document against exactly this one.
SCHEMA = "1.6.0"


def asset_url(version: str) -> str:
    return f"https://github.com/{REPO}/releases/download/v{version}/{ASSET}"


def sha256_of(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        digest = hashlib.sha256()
        while chunk := response.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest().upper()


def version_manifest(version: str) -> str:
    return f"""\
# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.{SCHEMA}.schema.json
PackageIdentifier: {PACKAGE}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: {SCHEMA}
"""


def locale_manifest(version: str) -> str:
    return f"""\
# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.{SCHEMA}.schema.json
PackageIdentifier: {PACKAGE}
PackageVersion: {version}
PackageLocale: en-US
Publisher: mfeminer
PublisherUrl: https://github.com/mfeminer
PublisherSupportUrl: https://github.com/{REPO}/issues
PackageName: lane
PackageUrl: https://github.com/{REPO}
License: MIT
LicenseUrl: https://github.com/{REPO}/blob/main/LICENSE
ShortDescription: Run several pieces of work side by side, each in its own git worktree
Description: |-
  A lane is one task: its own working copy, its own branch, its own editor window.
  lane creates the worktree and the branch when you start something, and clears both
  away once the work has landed — so there is no stashing and no checking out between
  half-finished jobs.

  lane is touched at the two ends only. You open a lane when you start, and close it
  when the work has landed; it is not part of the edit-test loop.
Tags:
  - git
  - worktree
  - cli
  - developer-tools
  - productivity
ReleaseNotesUrl: https://github.com/{REPO}/releases/tag/v{version}
ManifestType: defaultLocale
ManifestVersion: {SCHEMA}
"""


def installer_manifest(version: str, digest: str) -> str:
    return f"""\
# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.{SCHEMA}.schema.json
PackageIdentifier: {PACKAGE}
PackageVersion: {version}
InstallerType: portable
# lane is one self-contained binary and installs nothing else, which is what
# `portable` means here: winget puts it on PATH under its own links directory and
# removes it again on uninstall. There is no installer to run and nothing in the
# registry — the same shape as the Homebrew formula on the other side.
Commands:
  - lane
ReleaseDate: RELEASE_DATE
Installers:
  - Architecture: x64
    InstallerUrl: {asset_url(version)}
    InstallerSha256: {digest}
ManifestType: installer
ManifestVersion: {SCHEMA}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="the released version, without the leading v")
    parser.add_argument(
        "--into",
        type=Path,
        default=Path(__file__).parent / "manifests",
        help="where to write the three files",
    )
    parser.add_argument(
        "--release-date",
        default="",
        help="ISO date of the release; read from the release when omitted",
    )
    args = parser.parse_args()

    version = args.version.removeprefix("v")
    url = asset_url(version)
    print(f"hashing {url}", file=sys.stderr)
    digest = sha256_of(url)
    print(f"sha256 {digest}", file=sys.stderr)

    args.into.mkdir(parents=True, exist_ok=True)
    installer = installer_manifest(version, digest)
    if args.release_date:
        installer = installer.replace("RELEASE_DATE", args.release_date)
    else:
        installer = (
            "\n".join(
                line for line in installer.splitlines() if not line.startswith("ReleaseDate:")
            )
            + "\n"
        )

    written = {
        f"{PACKAGE}.yaml": version_manifest(version),
        f"{PACKAGE}.locale.en-US.yaml": locale_manifest(version),
        f"{PACKAGE}.installer.yaml": installer,
    }
    for name, body in written.items():
        (args.into / name).write_text(body, encoding="utf-8")
        print(f"wrote {args.into / name}", file=sys.stderr)

    print(
        f"\nSubmit by copying these into microsoft/winget-pkgs at\n"
        f"  manifests/m/mfeminer/lane/{version}/\n"
        f"and opening a pull request. See packaging/winget/README.md.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
