# One obvious way to run each thing. AGENTS.md names these commands.
.PHONY: help install test lint fmt types check build repro clean

help:
	@echo "install  install dependencies into .venv (uv)"
	@echo "test     run the test suite"
	@echo "lint     ruff check + format check"
	@echo "fmt      ruff format (writes)"
	@echo "types    mypy --strict"
	@echo "check    lint + types + test"
	@echo "build    PyInstaller one-file -> dist/lane"
	@echo "repro    build twice, prove the two binaries are byte-identical"
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
	@echo "built: dist/lane"

repro:
	# Two builds of the same tree, compared. A Homebrew formula pins the release
	# binary's sha256, and cd.yml rebuilds rather than reusing when it re-runs
	# against an existing release — so the day this stops holding, a re-run
	# silently breaks `brew install` for everyone on that version, with no change
	# to lane's own version number to explain it. Run it after touching
	# build.yml, cd.yml or lane.spec; it is not in `check` because it is two full
	# builds and `check` is meant to be cheap enough to run constantly.
	#
	# PYTHONHASHSEED is the setting that matters: PyInstaller writes
	# base_library.zip by walking a set, and Python's per-process string hash
	# randomisation reorders it. SOURCE_DATE_EPOCH is set to match CI, though
	# measured on macOS it does nothing on its own.
	@set -e; \
	export SOURCE_DATE_EPOCH="$$(git show -s --format=%ct)"; \
	export PYTHONHASHSEED=0; \
	echo "SOURCE_DATE_EPOCH=$$SOURCE_DATE_EPOCH PYTHONHASHSEED=$$PYTHONHASHSEED"; \
	rm -rf build dist; \
	$(MAKE) --no-print-directory build >/dev/null; \
	first="$$(shasum -a 256 dist/lane | awk '{print $$1}')"; \
	echo "  first   $$first"; \
	rm -rf build dist; \
	$(MAKE) --no-print-directory build >/dev/null; \
	second="$$(shasum -a 256 dist/lane | awk '{print $$1}')"; \
	echo "  second  $$second"; \
	if [ "$$first" != "$$second" ]; then \
		echo "NOT reproducible: the two builds differ" >&2; \
		exit 1; \
	fi; \
	echo "reproducible: both builds are $$first"

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
