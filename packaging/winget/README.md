# The winget manifests

`winget install mfeminer.lane` is the Windows half of "easy to install", and it is
the only Windows package manager lane targets. The reason is narrow and it is the
whole reason: **winget ships with Windows 10 and 11**, so a user installs nothing
before the install command works. A Scoop bucket or a Chocolatey package cannot offer
that — each needs itself installed first, which is one more thing to explain to
somebody who only wanted lane. Listing is also free and public: a manifest submitted
as a pull request to [microsoft/winget-pkgs][pkgs], with no paid tier and no review
gate beyond the automated validation.

There is deliberately **no Scoop bucket and no Chocolatey package**. If either is ever
wanted it is its own decision, made on its own merits.

[pkgs]: https://github.com/microsoft/winget-pkgs

## Why the generator lives here and the manifests do not

`generate.py` is committed; `manifests/` is gitignored. Same reasoning as
`src/lane/_version.py`: the manifest carries a version number and a hash, and a second
copy of a version number in the tree is only ever wrong later. What is worth keeping is
the thing that can rewrite them correctly from the release.

## Why the generator lives here at all

Same reason the Homebrew formula does not: winget's catalogue is not ours to hold.
The files in `manifests/` are the **source** for what gets submitted, kept beside the
thing they describe so a version bump is not archaeology. The published copy lives in
`microsoft/winget-pkgs` under `manifests/m/mfeminer/lane/<version>/`.

## What a release needs

The manifest pins the release asset's URL and its `sha256`, exactly as the Homebrew
formula does and for the same reason: a moving `releases/latest/download/...` pointer
has no checksum that can stay true, and winget's validation rejects a mismatch.

So every release needs the three files under `manifests/` regenerated and submitted.
`make winget VERSION=0.2.0` writes them from the published release — it downloads the
asset, hashes it, and fills the template — and prints the submission command.

**A published manifest freezes that release's asset.** Do not re-run `cd.yml` against
a tag whose manifest is already in `winget-pkgs`: the rebuild would change the
asset's `sha256` and every `winget install` of that version would start failing its
hash check. On macOS reproducibility makes that harmless in practice; on Windows it
is measured not to hold, so here the rule is the only protection. AGENTS.md carries
the full version of this under *Reproducibility is one platform's guarantee*.

## Submitting

```bash
make winget VERSION=0.2.0            # writes manifests/ from the published release
winget validate --manifest packaging/winget/manifests   # optional, needs Windows
```

Then open the pull request against [microsoft/winget-pkgs][pkgs], copying the three
files to `manifests/m/mfeminer/lane/<version>/`. `wingetcreate submit` automates the
same thing from a Windows machine and is the shorter route if one is to hand.
