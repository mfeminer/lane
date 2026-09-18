# One obvious way to run each thing. AGENTS.md names these commands.
.PHONY: help install test lint fmt types check build repro clean

# PyInstaller names the executable after the platform it is building for, so the
# two targets below have to as well. `OS` is set to `Windows_NT` by Windows itself
# and by nothing else.
ifeq ($(OS),Windows_NT)
BINARY := dist/lane.exe
else
BINARY := dist/lane
endif

help:
	@echo "install  install dependencies into .venv (uv)"
	@echo "test     run the test suite"
	@echo "lint     ruff check + format check"
	@echo "fmt      ruff format (writes)"
	@echo "types    mypy --strict"
	@echo "check    lint + types + test"
	@echo "build    PyInstaller one-file -> dist/lane (dist/lane.exe on Windows)"
	@echo "repro    build twice, compare the two binaries (holds on macOS, not on Windows)"
	@echo "clean    remove build artefacts"

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

types:
	uv run mypy

check: lint types test

build:
	# _version.py is written from the git tag at install time, so a tag created
	# since the last sync would otherwise be baked in stale. Re-install first and
	# the binary always reports the tag it was actually built from.
	uv sync --reinstall-package lane
	uv run pyinstaller --clean --noconfirm lane.spec
	@echo "built: $(BINARY)"

repro:
	# Two builds of the same tree, compared. A Homebrew formula and a Scoop manifest
	# both pin the release binary's sha256, and cd.yml rebuilds rather than reusing
	# when it re-runs against an existing release — so the day this stops holding, a
	# re-run silently breaks `brew install` for everyone on that version, with no
	# change to lane's own version number to explain it. Run it after touching
	# build.yml, cd.yml or lane.spec; it is not in `check` because it is two full
	# builds and `check` is meant to be cheap enough to run constantly.
	#
	# PYTHONHASHSEED is the setting that matters **on macOS**: PyInstaller writes
	# base_library.zip by walking a set, and Python's per-process string hash
	# randomisation reorders it. SOURCE_DATE_EPOCH is set to match CI, though
	# measured on macOS it does nothing on its own.
	#
	# **On Windows this target fails, and it is meant to.** Measured on a
	# windows-latest runner with both settings on, two builds of the same commit
	# differ: base_library.zip comes out with the same 155 members, the same contents
	# and the same timestamps, in a different order. AGENTS.md carries what that costs
	# and what stands in for it. Do not "fix" this by skipping the comparison there.
	@set -e; \
	export SOURCE_DATE_EPOCH="$$(git show -s --format=%ct)"; \
	export PYTHONHASHSEED=0; \
	echo "SOURCE_DATE_EPOCH=$$SOURCE_DATE_EPOCH PYTHONHASHSEED=$$PYTHONHASHSEED"; \
	if command -v shasum >/dev/null 2>&1; then sha="shasum -a 256"; \
	elif command -v sha256sum >/dev/null 2>&1; then sha="sha256sum"; \
	else echo "no shasum or sha256sum on PATH — cannot compare" >&2; exit 1; fi; \
	rm -rf build dist; \
	$(MAKE) --no-print-directory build >/dev/null; \
	first="$$($$sha $(BINARY) | awk '{print $$1}')"; \
	echo "  first   $$first"; \
	rm -rf build dist; \
	$(MAKE) --no-print-directory build >/dev/null; \
	second="$$($$sha $(BINARY) | awk '{print $$1}')"; \
	echo "  second  $$second"; \
	if [ -z "$$first" ] || [ -z "$$second" ]; then \
		echo "no hash was produced — this target proved nothing" >&2; \
		exit 1; \
	fi; \
	if [ "$$first" != "$$second" ]; then \
		echo "NOT reproducible: the two builds differ" >&2; \
		exit 1; \
	fi; \
	echo "reproducible: both builds are $$first"

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
