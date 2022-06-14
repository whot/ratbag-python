# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = doc/
BUILDDIR      = build
PYTHON_SOURCES	:= $(shell git ls-files "*.py")
MAKEFLAGS     = -j1


all: data black pytest html data mypy doctest

data:
	@if ! [[ -e data ]]; then echo "ERROR: symlink libratbag.git/data to this directory first" && exit 1; fi

black: $(PYTHON_SOURCES)
	black $(PYTHON_SOURCES)

pytest: data $(PYTHON_SOURCES)
	pytest

mypy: $(PYTHON_SOURCES)
	mypy ratbag tests

doctest: $(PYTHON_SOURCES)
	python -m doctest $(PYTHON_SOURCES)

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile

html: Makefile
	mkdir -p $(BUILDDIR)
	cp -r $(SOURCEDIR)/* $(BUILDDIR)/
	@$(SPHINXBUILD) -M $@ "$(BUILDDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

clean:
	test -n "$(BUILDDIR)" -a "$(BUILDDIR)" != "/" -a "$(BUILDDIR)" != "." -a "$(BUILDDIR)" != ".." && rm -rf $(BUILDDIR)/
