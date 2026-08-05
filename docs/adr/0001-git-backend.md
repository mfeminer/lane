# ADR 0001 — How lane talks to git

- **Status:** accepted
- **Date:** 2026-08-04
- **Decides:** which git backend sits behind `GitBackend`, and whether the `git`
  CLI is a runtime prerequisite

## Context

lane's whole job is the git worktree lifecycle: create a worktree on a new branch
with no upstream, or on a detached HEAD at `origin/<default>`; inspect it; remove
it and clean up. The brief's stated preference was a real library over shelling
out, with the decision to be made on evidence rather than preference.

Four candidates were spiked against seven criteria, using scratch repositories
built locally (a bare "remote" plus a clone), plus a separate authentication
investigation against repositories already cloned on this machine. The spike code
has been deleted; this ADR is its durable output.

Versions tested: pygit2 1.19.3 (libgit2 1.9.4), dulwich 1.2.12, GitPython 3.1.57,
git 2.50.1 (Apple Git-155), Python 3.12.12, PyInstaller 6.x, macOS arm64.

The spike ran on Python 3.12; lane itself targets **3.14** (see `AGENTS.md`). This
does not affect the decision — the recommendation spawns `git` and imports no git
library — and the packaging evidence was re-verified on 3.14.6 with PyInstaller
6.21.0: a one-file binary carrying `prompt_toolkit`, `rich` and `tomli-w` builds and
runs. Nothing here rests on the interpreter version; the pygit2 dylib collision is
between the wheel's bundled OpenSSL and CPython's `_ssl`, which is a property of the
wheel, not of 3.12.

## Evidence

### The seven criteria

| # | Criterion | pygit2 | dulwich | GitPython | git CLI |
|---|---|:---:|:---:|:---:|:---:|
| 1 | Worktree on a new branch, no upstream | pass¹ | pass | pass² | **pass** |
| 2 | Worktree on a detached HEAD at `origin/<default>` | **fail** | pass | pass² | **pass** |
| 3 | Remove a worktree (incl. dirty) and prune | **fail** | pass³ | pass² | **pass** |
| 4 | `fetch --prune` from a local bare remote | pass | pass | pass² | **pass** |
| 5 | Status, ahead/behind, ancestry | **pass** | pass⁴ | pass² | pass |
| 6 | Delete a branch, with and without the merged check | partial⁵ | partial⁵ | pass² | **pass** |
| 7 | Detect the remote default branch | pass | pass | pass² | **pass** |

¹ Only by pre-creating the branch and passing its ref. `add_worktree(name, path)`
with no ref names the branch after the *worktree*, coupling two things lane needs
to set independently (worktree at `<lanes_root>/<project>/<lane>`, branch at
`feature/<slug>`).

² GitPython passes everything because it *is* the git CLI. `Repo` has no worktree
abstraction whatsoever — you write `repo.git.worktree("add", "--no-track", …)`,
which is the same command string and the same text parsing as `subprocess`, with
an object wrapper and a dependency on top. It does not remove the `git`
requirement it appears to remove: `Git.execute` is `subprocess.Popen`, and
`GIT_PYTHON_GIT_EXECUTABLE` defaults to `git`.

³ dulwich has a genuinely complete worktree API — `worktree_add`,
`worktree_remove`, `worktree_prune`, `worktree_list`, `_lock`, `_move`, `_repair`
— which contradicted the brief's starting assumption and was the spike's main
surprise. But see *dulwich discards uncommitted work* below.

⁴ `porcelain.is_ancestor` exists and works. Ahead/behind has no helper and must be
hand-walked with `get_walker(include=…, exclude=…)`; `status()` returns a
dataclass of byte-string lists.

⁵ Both libraries' branch deletion is unconditional — the equivalent of
`git branch -D`. Neither has a `-d`: the "is it merged?" check must be
reimplemented before calling it. Getting that check subtly wrong is how a user
loses commits, and it is exactly the check lane asks the user to override
deliberately.

### The failures that decide it

**pygit2 cannot create a detached worktree (criterion 2).** `add_worktree` rejects
anything that is not a local branch:

```
add_worktree("c2", path, repo.lookup_reference("refs/remotes/origin/main"))
  -> _pygit2.GitError: reference is not a branch
```

A tag ref is rejected the same way. libgit2 has no `--detach` equivalent. The only
route is a three-step dance — create a throwaway branch, `add_worktree` on it,
`set_head(oid)` inside the worktree to detach, then delete the throwaway branch —
which was verified to work but leaves a window in which a stray branch exists, and
relies on `set_head` against a linked-worktree repository for a purpose it is not
documented for. Detached mode is one of lane's two lane modes, not an edge case.

**pygit2 cannot remove a worktree at all (criterion 3).** The entire `Worktree`
API is `is_prunable`, `name`, `path`, `prune`. There is no `remove`, on
`Worktree`, on `Repository`, or in `pygit2.enums`. `prune()` on a live worktree
correctly refuses (`not pruning valid working tree`), so removal means
`shutil.rmtree` followed by `prune()`. That was verified to leave `git worktree
list` clean — but it means lane reimplements what `git worktree remove` does for
free: refusing a dirty tree unless forced, refusing a locked worktree, and
removing the tree and its admin directory together.

**Neither library can authenticate the way this machine is configured.** This is
the criterion a local bare remote cannot test, so it was checked against real
remote URLs taken from repositories under the projects root, read-only
(`ls-remote`-equivalent handshakes only; nothing was written and no pack was
transferred into them).

SSH — `git@github.com:acme/Acme.Widgets.git`:

| | Result |
|---|---|
| git CLI | **OK** — 1906 refs, `HEAD -> refs/heads/dev` |
| dulwich | **OK** — 1906 refs, because its default SSH vendor is `SubprocessSSHVendor`, i.e. it shells out to the `ssh` binary |
| pygit2 | **fail** without help: `authentication required but no callback set`. With `KeypairFromAgent`: fails (this machine's agent holds no identities). With an explicit `pygit2.Keypair("git", ~/.ssh/id_ed25519.pub, ~/.ssh/id_ed25519, "")`: **OK**, 1906 refs |

So pygit2 *can* do SSH — but only if lane itself owns SSH key discovery: reading
`~/.ssh/config`, honouring `IdentityFile` and host aliases, falling back to the
agent, and prompting for passphrases on encrypted keys. That is precisely the
"owning token storage, device flows and keychain handling" burden the brief
rejected for GitHub, arriving through a different door.

HTTPS with credentials — **could not be positively verified for any candidate**;
see *Open question* below. What *was* established does not depend on a test
repository: **neither library implements git's credential-helper protocol.**
`dulwich.credentials` is URL/config *parsing* only (`match_urls`,
`urlmatch_credential_sections`) with no helper subprocess invocation anywhere;
pygit2's credential surface (`Keypair`, `UserPass`, `KeypairFromAgent`, …) is
entirely objects *you* construct and hand over. Nothing in either consults
`credential.helper` — `osxkeychain` on this machine. Both failed the one HTTPS
endpoint tried (`HTTPUnauthorized: No valid credentials provided` for dulwich;
`remote authentication required but no callback set` for pygit2).

**pygit2 does not bundle cleanly under PyInstaller one-file.** The brief asked for
this to be verified early. It fails, in two stages:

1. `ModuleNotFoundError: No module named '_cffi_backend'` — fixable with
   `--hidden-import=_cffi_backend`.
2. Then, unfixed after three attempts:

   ```
   ImportError: dlopen(.../_ssl.cpython-312-darwin.so):
     Symbol not found: _CRYPTO_calloc
     Referenced from: <...>/libssl.3.dylib
     Expected in:     <...>/pygit2/.dylibs/libcrypto.3.dylib
   ```

   The pygit2 wheel ships its own `libcrypto.3.dylib` (and `libssh2`, `libgit2`)
   under `pygit2/.dylibs/`. PyInstaller deduplicates collected binaries by
   basename, so pygit2's `libcrypto.3.dylib` displaces Homebrew's — and CPython's
   `_ssl`, linked against Homebrew's `libssl.3.dylib` + `libcrypto.3.dylib`, then
   resolves against the wrong OpenSSL build. pygit2 fails to *import*, so the
   binary cannot start at all.

   Workarounds tried: (a) drop pygit2's duplicate OpenSSL — fails, `libssh2` needs
   it (`Library not loaded: @rpath/libcrypto.3.dylib`); (b) add Homebrew's
   `libcrypto` back at the root of the bundle — fails, PyInstaller's dylib-rewriting
   pass still repoints `libssl` at pygit2's copy; (c) build pygit2 from source
   against Homebrew's libgit2 so one OpenSSL is shared — needs `libgit2` headers
   installed (`fatal error: 'git2.h' file not found`), meaning a source build, a
   compiler, and `libgit2` on every build machine, with the dylib then to be
   bundled and relinked by hand.

   None of this is unsolvable, but all of it is `install_name_tool` surgery in the
   build that breaks on any pygit2, OpenSSL, Python or PyInstaller bump. `make
   build` is supposed to be boring.

**dulwich discards uncommitted work without being asked.**
`worktree_remove(repo, path, force=False)` deleted a worktree containing an
untracked file, where `git worktree remove` refuses:

```
git worktree remove <dirty>   -> rc=128, "fatal: ... contains modified or untracked files"
dp.worktree_remove(..., force=False) -> deleted it; directory gone
```

lane's most destructive operation is closing a lane, and the safety it advertises
is "nothing is left behind by accident". A backend whose non-forced removal is
git's *forced* removal inverts that default.

### Secondary findings

- **Ref-name validation.** The brief requires validation with
  `git check-ref-format`. `pygit2.reference_is_valid_name` disagrees with it on 2
  of 18 probed names — it accepts `-leading` and `HEAD`, both of which
  `check-ref-format --branch` rejects. Both are plausible hand-typed branch names.
- **Startup cost**, paid on every invocation of a tool that runs, does one thing
  and exits: `import dulwich.porcelain` 92 ms, `import pygit2` 47 ms,
  `import subprocess` 4 ms.
- **Binary size / build**, PyInstaller one-file: subprocess 6.9 MB / 5.0 s,
  pygit2 7.9 MB / 7.7 s (does not run), dulwich 12 MB / 9.2 s.
- **dulwich output hygiene.** `porcelain.fetch` writes progress
  (`counting objects: 6, done.`) to stdout by default, and interpreter shutdown
  produced `ImportError: sys.meta_path is None` spam from `__del__` methods in
  `object_store`/`pack`. Both are manageable but both fight a clean TUI.
- **Listing performance is not a reason to avoid subprocess.** 12 lanes × 4 git
  calls = 48 processes: 800 ms sequentially, **161 ms** across 8 threads (5.0×;
  threads work because subprocesses release the GIL). A 12-lane listing renders in
  about a sixth of a second.
- **The bash version's default-branch fallback has a real bug.** Its last resort
  probes `main`, `master`, `develop` — and this machine's primary repository,
  `Acme.Widgets`, has default branch **`dev`**, which that list misses. Reading
  `origin/HEAD` and `git remote set-head origin --auto` both resolve it correctly
  (verified against `main`, `master` and `dev` fixtures). The hardcoded probe must
  stay a genuine last resort, and when all else fails lane should say it could not
  determine the default branch rather than guess `main`.

## Decision

**Pure subprocess against the `git` CLI**, behind the `GitBackend` interface.

Consequently **`git` is a runtime prerequisite**, checked at startup rather than
per action, since nothing lane does works without it. The refusal names what is
missing and keeps the two standing exemptions: `--version` and `--help` are
answered before any prerequisite is consulted, and doctor is always reachable.

`GitPython` is rejected as strictly worse than the thing it wraps: it requires the
same `git` binary, gives no worktree abstraction, and adds a dependency and a layer
of exception translation for nothing.

## Why not a hybrid

A hybrid — library for read-only inspection, `git` CLI for the worktree lifecycle —
was a legitimate candidate and the brief invited it explicitly. It is rejected on
the evidence:

- **pygit2 for inspection is the strongest technical case in the spike** (criterion
  5 is genuinely better than parsing porcelain) **and it is still dead**, because
  the packaging failure is at *import* time. Using pygit2 for one read-only
  purpose costs the entire OpenSSL dylib problem.
- **dulwich for inspection** packages cleanly, but buys little: it adds 92 ms to
  every startup and 5 MB to the binary, has no ahead/behind helper, returns byte
  lists, and prints progress to stdout — to avoid parsing porcelain output that is
  stable, documented, and already parsed correctly by the reference implementation.
- Either hybrid means **two independent git implementations reading the same
  repositories**, so a disagreement between them becomes a class of bug that the
  single-backend design cannot have. For a tool whose entire value is being trusted
  not to lose work, that is a bad trade.
- The performance argument for a library does not survive measurement: 161 ms for a
  12-lane listing.

## Consequences

**Accepted costs.**

- Text output must be parsed. Mitigated by using only stable, machine-oriented
  forms — `--porcelain`, `rev-list --count`, `show-ref --verify --quiet`,
  `--abbrev-ref`, `merge-base --is-ancestor` (exit-code only) — never
  human-readable output, and never localised output. The backend sets
  `LC_ALL=C`/`GIT_CONFIG_NOSYSTEM`-style guards where a user's config could
  otherwise change what it reads.
- Process-spawn overhead, ~13 ms per git call. Handled by collecting the listing's
  per-lane status across a thread pool.
- `git` must be on PATH, checked at startup, reported by doctor.

**Gains beyond the criteria.**

- git enforces its own safety rules, so lane inherits them rather than
  reimplementing them: `worktree remove` refuses a dirty tree, `branch -d` refuses
  an unmerged branch. Both are checks lane deliberately asks the user to override,
  and both stay git's to make.
- Authentication is whatever the user has already configured — SSH agent,
  `~/.ssh/config`, `osxkeychain`, Azure DevOps, enterprise setups — with no
  credential handling in lane at all. This matters more than any other single
  point: it is the same reasoning that settled `gh`, applied to git.
- `make build` stays boring: no compiled dependency, no dylib surgery, the smallest
  and fastest binary of the three.
- The `GitBackend` seam is unchanged by this. If libgit2 grows worktree removal and
  a detached-worktree option, and pygit2's wheels stop colliding with CPython's
  OpenSSL, the implementation can be swapped without the rest of the application
  noticing — which is the reason the seam exists.

## Open question for the maintainer

**HTTPS-with-credentials could not be verified on this machine, and the brief asks
me not to guess.** Under the projects root there are two kinds of HTTPS origin:

- Azure DevOps (`https://contoso.visualstudio.com/...`, four repositories) — no
  usable cached credential. `GIT_TERMINAL_PROMPT=0 git ls-remote` fails with
  `could not read Username for 'https://contoso.visualstudio.com'`, so the **git
  CLI itself** cannot authenticate there non-interactively; nothing can be
  concluded about a library from it.
- `https://github.com/asalih/plaso.git` — public, so it succeeds without
  credentials and proves nothing about credential handling.

SSH was fully testable and is reported above. **This does not block the decision**:
the recommended backend is the git CLI, which is the baseline every candidate was
measured against and which by construction uses the machine's own credential
configuration. The gap would only matter if we were choosing between libraries,
and there the structural finding already stands on its own — neither implements
git's credential-helper protocol, which is what makes HTTPS work on this machine.

If you want the empirical HTTPS result on the record anyway, point me at a
repository whose `origin` is HTTPS and whose credentials are cached (or log in to
one of the Azure DevOps remotes) and I will add it here.
