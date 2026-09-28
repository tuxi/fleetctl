# fleetctl Makefile
# Cross-platform build, test, and packaging automation.

SHELL := /bin/bash
VERSION := $(shell python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null || echo "0.0.0")
DIST_DIR := dist
BUILD_DIR := build
APP_NAME := fleetctl
ENTRY := fleetctl/main.py

.PHONY: help install dev test test-cov lint format type-check clean-build \
        build binary dmg msi appimage package release changelog

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- #
# 安装与开发环境                                                     #
# ---------------------------------------------------------------- #

install: ## Install package
	pip install .

dev: ## Install with dev + pdf dependencies (editable)
	pip install -e ".[dev,pdf]"

# ---------------------------------------------------------------- #
# 测试与质量                                                         #
# ---------------------------------------------------------------- #

test: ## Run full test suite
	python -m pytest -q

test-cov: ## Run tests with coverage report
	python -m pytest --cov=fleetctl --cov-report=term-missing --cov-report=html

lint: ## Run ruff linter
	ruff check fleetctl tests || true

format: ## Format with black
	black fleetctl tests

type-check: ## Run mypy
	mypy fleetctl || true

check: lint type-check test ## Run all quality gates

# ---------------------------------------------------------------- #
# 构建                                                               #
# ---------------------------------------------------------------- #

clean-build: ## Remove build artifacts
	rm -rf $(BUILD_DIR) $(DIST_DIR) *.spec.bak
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage

build: clean-build ## Build Python sdist + wheel
	pip install build
	python -m build

binary: ## Build standalone binary with PyInstaller
	pip install pyinstaller
	pyinstaller --clean --noconfirm \
		--name $(APP_NAME) \
		--onefile \
		--console \
		--collect-all pymobiledevice3 \
		--hidden-import pymobiledevice3.services.mobile_config \
		--hidden-import pymobiledevice3.services.diagnostics \
		--hidden-import pymobiledevice3.services.installation_proxy \
		fleetctl/main.py
	@echo "Binary: $(DIST_DIR)/$(APP_NAME)"

# ---------------------------------------------------------------- #
# 多平台打包                                                         #
# ---------------------------------------------------------------- #

dmg: binary ## Build macOS .dmg (run on macOS)
	bash scripts/package-macos.sh "$(VERSION)"

msi: ## Build Windows .msi (run on Windows)
	powershell -ExecutionPolicy Bypass -File scripts/package-windows.ps1 -Version "$(VERSION)"

appimage: binary ## Build Linux .AppImage (run on Linux)
	bash scripts/package-linux.sh "$(VERSION)"

package: ## Build for current platform (auto-detect)
	@case "$$(uname -s)" in \
		Darwin) $(MAKE) dmg ;; \
		Linux)  $(MAKE) appimage ;; \
		MINGW*|MSYS*|CYGWIN*) $(MAKE) msi ;; \
		*) echo "Unsupported platform: $$(uname -s)"; exit 1 ;; \
	esac

# ---------------------------------------------------------------- #
# 发布                                                               #
# ---------------------------------------------------------------- #

changelog: ## Generate changelog from git log
	@echo "# Changelog" > CHANGELOG.md
	@echo "" >> CHANGELOG.md
	@git log --pretty=format:'- %s (%h)' >> CHANGELOG.md
	@echo "" >> CHANGELOG.md
	@echo "CHANGELOG.md updated"

release: changelog build package ## Build release artifacts
	@echo "Release $(VERSION) artifacts in $(DIST_DIR)/"
	@ls -la $(DIST_DIR)/
