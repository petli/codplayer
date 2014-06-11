
JSHINT = ./node_modules/.bin/jshint

REPORTER=
ifeq ($(EMACS),t)
REPORTER=--reporter=.jshint-emacs.js
endif

all: lint

lint: server.js
	$(JSHINT) $(REPORTER) $^

.PHONY: all lint
