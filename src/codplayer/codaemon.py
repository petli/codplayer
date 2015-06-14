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

# http://www.python.org/dev/peps/pep-3143/
import daemon
import lockfile

from . import full_version

class DaemonError(Exception): pass

class Daemon(object):
    def __init__(self, cfg, debug = False):
        self._log_debug = debug

        preserve_files = []

        if debug:
            self._log_file = sys.stderr
        else:
            try:
                self._log_file = open(cfg.log_file, 'at')
            except IOError, e:
                sys.exit('error opening {0}: {1}'.format(cfg.log_file, e))

            preserve_files.append(self._log_file)


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
        self.log('starting {}', full_version())

        if debug:
            # Just run directly without forking off.
            self.setup_prefork()
            self.setup_postfork()
            self._drop_privs()
            self.run()

        else:
            context = daemon.DaemonContext(
                files_preserve = preserve_files,
                pidfile = lockfile.FileLock(cfg.pid_file),
                stdout = log_file,
                stderr = log_file,
                )

            # Run in daemon context, forking off and all that
            self.setup_prefork()
            with context:
                self.setup_postfork()
                self._drop_privs()
                self.run()


    def _drop_privs(self):
        # Drop any privs to get ready for full operation.  Do this
        # before opening the sink, since we generally need to be
        # able to reopen it with the reduced privs anyway
        if self._uid and self._gid:
            if os.geteuid() == 0:
                try:
                    self.log('dropping privs to uid {0} gid {1}',
                             self._uid, self._gid)

                    os.setgid(self._gid)
                    os.setuid(self._uid)
                except OSError, e:
                    raise DaemonError("can't set UID or GID: {0}".format(e))
            else:
                self.log('not root, not changing uid or gid')


    def run(self):
        raise NotImplementedError()

    def setup_prefork(self):
        pass

    def setup_postfork(self):
        pass


    def log(self, msg, *args, **kwargs):
        m = (time.strftime('%Y-%m-%d %H:%M:%S ') + threading.current_thread().name + ': '
             + msg.format(*args, **kwargs) + '\n')
        self._log_file.write(m)
        self._log_file.flush()


    def debug(self, msg, *args, **kwargs):
        if self._log_debug:
            self.log(msg, *args, **kwargs)

