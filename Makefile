# Riff developer command surface
.PHONY: help lint format typecheck test test-cov run install-dev pre-commit build-flatpak lock check

export PATH := $(HOME)/.local/bin:$(PATH)
UV ?= uv

help:
	@echo "Targets: lint format typecheck test test-cov check run install-dev pre-commit lock build-flatpak"

install-dev:
	$(UV) sync --all-extras --group dev
	$(UV) pip install -e ".[dev,ai]"

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck:
	$(UV) run mypy riff/core

test:
	$(UV) run pytest -q

test-cov:
	$(UV) run pytest -q --cov=riff/core --cov-report=term-missing --cov-fail-under=60

check: lint
	$(UV) run ruff format --check .
	$(MAKE) typecheck
	$(MAKE) test-cov

run:
	$(UV) run riff

pre-commit:
	$(UV) run pre-commit install

lock:
	$(UV) lock
