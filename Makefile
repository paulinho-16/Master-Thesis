SHELL := /bin/bash

# Get the variable from a given section in the `config.ini` file
SUMO_PATH := $(shell powershell.exe -Command "Get-Content config.ini | ForEach-Object { if ($$_ -match '\[dir\]') { $$section = $$true } elseif ($$section -and $$_ -match '^SUMO=([^;]+)') { $$matches[1].Trim() } }")

# Replace all occurrences of "/" with "\"
SUMO_PATH := $(subst /,\,$(SUMO_PATH))

CALIBRATORS_FILE = $(SUMO_PATH)\calibrators.add.xml

.PHONY: all

all: prepare run

prepare:
	@python -m src.prepare

solve:
	@python -m src.solver

run:
	@python -m src.digital_twin

clean:
	@PowerShell -Command "Write-Output 'Removing files...'"
	del $(CALIBRATORS_FILE)