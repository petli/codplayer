
JSHINT = ../../../../controlwidget/node_modules/.bin/jshint

REPORTER=
ifeq ($(EMACS),t)
REPORTER=--reporter=.jshint-emacs.js
endif

all: lint

lint: codadmin.js
	$(JSHINT) $(REPORTER) $^

.PHONY: all lint
