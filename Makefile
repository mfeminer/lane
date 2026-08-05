# One obvious way to run each thing. AGENTS.md names these commands.
.PHONY: help install test lint fmt types check build clean

help:
	@echo "install  install dependencies into .venv (uv)"
	@echo "test     run the test suite"
	@echo "lint     ruff check + format check"
	@echo "fmt      ruff format (writes)"
	@echo "types    mypy --strict"
	@echo "check    lint + types + test"
	@echo "build    PyInstaller one-file -> dist/lane"
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
	uv run pyinstaller --clean --noconfirm lane.spec
	@echo "built: dist/lane"

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
