# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = doc/
BUILDDIR      = build


all: data black pytest html data

data:
	@if ! [[ -e data ]]; then echo "ERROR: symlink libratbag.git/data to this directory first" && exit 1; fi

black: **/*.py *.py
	black *.py **/*.py

pytest: data
	pytest

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile

html: Makefile
	mkdir -p $(BUILDDIR)
	cp -r $(SOURCEDIR)/* $(BUILDDIR)/
	@$(SPHINXBUILD) -M $@ "$(BUILDDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
