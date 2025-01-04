.DEFAULT_GOAL := all
SHELL := /bin/bash

ifeq ($(OS),Windows_NT)
	ifeq ($(VENV_BIN_ACTIVATE),)
		VENV_BIN_ACTIVATE := .venv/Scripts/activate
	endif
	BIN := twitch-obs-dice.exe
	export MSYS_NO_PATHCONV = 1
else
	ifeq ($(VENV_BIN_ACTIVATE),)
		VENV_BIN_ACTIVATE := .venv/bin/activate
	endif
	BIN := twitch-obs-dice
endif

OBJ := main.py
OBJ += README.md

$(VENV_BIN_ACTIVATE): requirements.txt
	@echo "[info] Setting up development virtual env in .venv"
	python -m venv --system-site-packages .venv
	@set -e; \
	. $(VENV_BIN_ACTIVATE); \
	python -m pip install wheel
	@echo "[info] Installing dependencies"
	@set -e; \
	. $(VENV_BIN_ACTIVATE); \
	python -m pip install \
		--extra-index-url=https://wheels.eeems.codes/  \
	    -r requirements.txt

clean:
	@echo "[info] Cleaning"
	git clean --force -dX

executable: $(VENV_BIN_ACTIVATE)
	@echo "[info] Installing pyinstaller"
	@set -e; \
	. $(VENV_BIN_ACTIVATE); \
	python -m pip install pyinstaller
	@echo "[info] Building twitch-obs-dice"
	@set -e; \
	. $(VENV_BIN_ACTIVATE); \
	python -m PyInstaller \
	    --onefile \
	    --name twitch-obs-dice \
	    main.py
	if [ -d dist/twitch-obs-dice.build ]; then \
	    rm -r dist/twitch-obs-dice.build; \
	fi
	cp config.example.toml dist/

all: executable

.PHONY: \
	all \
	executable \
	clean \
	test \
	test-executable
