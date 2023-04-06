SHELL := /bin/bash

CONFIG_FILE = config.ini

# Get the variable from a given section in the configuration file
define get_variable
$(subst /,\,$(shell powershell.exe -Command "Get-Content $(CONFIG_FILE) | ForEach-Object { if ($$_ -match '\[$(1)\]') { $$section = $$true } elseif ($$section -and $$_ -match '^$(2)=([^;]+)') { $$matches[1].Trim() } }"))
endef

# Get the filename from a path
define get_filename
$(shell powershell.exe -NoProfile -Command "Split-Path '$1' -Leaf")
endef

SUMO_PATH := $(call get_variable,dir,SUMO)
CALIBRATORS_FILENAME := $(call get_filename, $(call get_variable,sumo,CALIBRATORS))
CALIBRATORS_FILE = $(SUMO_PATH)\$(CALIBRATORS_FILENAME)

NODES_PATH := $(call get_variable,dir,NODES)
NODE_ARTICLE_FILENAME := $(call get_filename, $(call get_variable,nodes,NODE_ARTICLE))
NODE_ARTICLE_FILE = $(NODES_PATH)\$(NODE_ARTICLE_FILENAME)

.PHONY: all

all: prepare run

# TODO: Run the netconvert command on all node networks
prepare:
	netconvert -s $(NODE_ARTICLE_FILE) -o $(NODE_ARTICLE_FILE) --remove-edges.isolated true
	@python -m src.prepare

variables:
	@python -m src.variables

solve:
	@python -m src.solver

run:
	@python -m src.digital_twin

clean:
	@PowerShell -Command "Write-Output 'Removing files...'"
	del $(CALIBRATORS_FILE)