
JSHINT = ./node_modules/.bin/jshint

REPORTER=
ifeq ($(EMACS),t)
REPORTER=--reporter=.jshint-emacs.js
endif

all: lint

lint: server.js static/codctl.js
	$(JSHINT) $(REPORTER) $^


dist:
	git clean -fx .
	npm pack

.PHONY: all lint dist
