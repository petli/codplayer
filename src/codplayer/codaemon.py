# codplayer - common logic for daemons
#
# Copyright 2013-2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

import sys
import os
import pwd
import grp
import threading
import time
import traceback

# http://www.python.org/dev/peps/pep-3143/
from daemon import DaemonContext
from lockfile.pidlockfile import PIDLockFile

from . import full_version
from . import zerohub

class DaemonError(Exception): pass

class Daemon(object):
    """Base class for all daemons.  Handles log files,
    dropping privileges, forking etc.
    """

    def __init__(self, cfg, debug = False, **kwargs):
        """Create and run a daemon.

        cfg: a DaemonConfig object
        debug: True if debug messages should be logged
        kwargs: anything else is passed to plugin constructors.
        """

        self._daemon_config = cfg
        self._log_debug = debug
        self._io_loop = None
        self._plugins = cfg.plugins or []

        self._preserve_files = []

        if debug:
            self._log_file = sys.stderr
        else:
            try:
                self._log_file = open(cfg.log_file, 'at')
            except IOError, e:
                sys.exit('error opening {0}: {1}'.format(cfg.log_file, e))

            self._preserve_files.append(self._log_file)


        # Figure out which IDs to run as, if any
        self._uid = None
        self._gid = None

        if cfg.user:
            try:
                pw = pwd.getpwnam(cfg.user)
                self._uid = pw.pw_uid
                self._gid = pw.pw_gid
            except KeyError:
                raise DaemonError('unknown user: {0}'.format(cfg.user))

        if cfg.group:
            if not cfg.user:
                raise DaemonError("can't set group without user in config")

            try:
                gr = grp.getgrnam(cfg.group)
                self._gid = gr.gr_gid
            except KeyError:
                raise DaemonError('unknown group: {0}'.format(cfg.user))

        # Now kick off the daemon

        self.log('-' * 60)
        self.log('starting {}', sys.argv[0])
        self.log('version: {}', full_version())
        self.log('configuration: {}', cfg.config_path)

        if debug:
            # Just run directly without forking off.
            self.setup_prefork()
            [p.setup_prefork(self, cfg, **kwargs) for p in self._plugins]
            self.setup_postfork()
            [p.setup_postfork() for p in self._plugins]
            self._drop_privs()
            [p.setup_prerun() for p in self._plugins]
            self.run()

        else:
            # Fail early if daemon appear to be locked
            pid_lock = PIDLockFile(path = cfg.pid_file, timeout = 0)
            if pid_lock.is_locked():
                sys.exit('daemon already running (pid {}) since lock file is present: {}'.format(
                    pid_lock.read_pid(), cfg.pid_file))

            # Run in daemon context, forking off and all that
            self.setup_prefork()
            [p.setup_prefork(self, cfg, **kwargs) for p in self._plugins]

            context = DaemonContext(
                initgroups = False, # We'll drop privs ourselves
                files_preserve = self._preserve_files,
                pidfile = pid_lock,
                stdout = self._log_file,
                stderr = self._log_file,
                )

            with context:
                self.setup_postfork()
                [p.setup_postfork() for p in self._plugins]
                self._drop_privs()
                [p.setup_prerun() for p in self._plugins]
                self.run()


    @property
    def config(self):
        return self._daemon_config


    def _drop_privs(self):
        # Drop any privs to get ready for full operation.  Do this
        # before opening the sink, since we generally need to be
        # able to reopen it with the reduced privs anyway
        if self._uid and self._gid:
            if os.geteuid() == 0:
                try:
                    self.log('dropping privs to uid {0} gid {1}, initgroups={2}',
                             self._uid, self._gid, self._daemon_config.initgroups)

                    if self._daemon_config.initgroups:
                        os.initgroups(self._daemon_config.user, self._gid)
                    else:
                        os.setgid(self._gid)

                    os.setuid(self._uid)
                except OSError, e:
                    raise DaemonError("can't set UID or GID: {0}".format(e))
            else:
                self.log('not root, not changing uid or gid')


    def preserve_file(self, fileno_object):
        """Add a fileno() object to the list of files to keep
        open across fork.  This only makes sense to call dfrom setup_prefork().
        """
        self._preserve_files.append(fileno_object)


    def run(self):
        """Override to implement the main logic of the daemon.
        This is called after forking and dropping privileges.
        """
        raise NotImplementedError()

    def setup_prefork(self):
        """Override to implement any setup that should be done before
        forking and dropping privileges.

        Any files opened in this method must be registered by calling
        Daemon.preserve_file(), otherwise it will not survive forking.
        """
        pass

    def setup_postfork(self):
        """Override to implement any setup that should be done after
        forking but before dropping privileges.
        """
        pass


    @property
    def io_loop(self):
        """Access the IOLoop instance for this daemon.  This should be used
        instead of IOLoop.instance(), since this one will stop the
        daemon on callback errors rather than just logging and continuing.
        """
        if self._io_loop is None:
            self._io_loop = DaemonIOLoop()
            self._io_loop.make_current()
            self._io_loop._cod_daemon = self
        return self._io_loop


    def log(self, msg, *args, **kwargs):
        text = msg.format(*args, **kwargs)
        if text is unicode:
            text = text.encode('utf-8')

        m = (time.strftime('%Y-%m-%d %H:%M:%S ') + threading.current_thread().name + ': '
             + text + '\n')
        self._log_file.write(m)
        self._log_file.flush()


    def debug(self, msg, *args, **kwargs):
        if self._log_debug:
            self.log(msg, *args, **kwargs)


class Plugin(object):
    """Plugins must inherit from this base class and implement the setup
    methods as applicable.
    """

    def setup_prefork(self, daemon, cfg, **kwargs):
        """Called after Daemon.setup_prefork().

        daemon: the main daemon object
        cfg: the main configuration object
        kwargs: any other arguments provided to the Daemon constructor
        """
        pass


    def setup_postfork(self):
        """Called after Daemon.setup_postfork().
        """
        pass


    def setup_prerun(self):
        """Called after dropping privileges, before Daemon.run()
        """
        pass


class DaemonIOLoop(zerohub.IOLoop):
    def handle_callback_exception(self, callback):
        self._cod_daemon.log('Unhandled exception:\n{}', traceback.format_exc())
        sys.exit(1)
