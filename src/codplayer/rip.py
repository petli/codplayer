# codplayer - rip discs into the database
#
# Copyright 2013-2014 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.


import os
import subprocess
import time

from musicbrainz2 import disc as mb2_disc

from . import serialize
from . import db
from . import model
from . import toc
from .state import RipState

class RipError(Exception): pass

class Ripper(object):
    """Class controlling the process of ripping a disc into the database.
    """

    def __init__(self, player):
        self.cfg = player.cfg
        self.db = player.db
        self.log = player.log
        self.debug = player.debug
        self.publishers = player.publishers

        self.state = RipState()
        # Clean out any previous state file
        self.update_state()

        self.disc = None
        self.db_id = None

        # The ripping process is split into tasks, each is a generator
        # that are called by the tick() method to check if the
        # supporting command has finished processing
        self.tasks = None
        self.current_task = None
        self.current_process = None

    def read_disc(self):
        """Read a physical disc and return a model.DbDisc instance
        representing it.

        If the disc is not yet ripped (or only partially ripped) this
        will (re)start the ripping process.
        """

        self.debug('disc inserted, reading ID')

        # Use Musicbrainz code to get the disc signature
        try:
            mbd = mb2_disc.readDisc(self.cfg.cdrom_device)
        except mb2_disc.DiscError, e:
            raise CommandError('error reading disc in {0}: {1}'.format(
                self.cfg.cdrom_device, e))

        # Look up in database
        db_id = self.db.disc_to_db_id(mbd.getId())
        old_disc = self.db.get_disc_by_db_id(db_id)
        new_disc = model.DbDisc.from_musicbrainz_disc(
            mbd, filename = self.db.get_audio_path(db_id))

        if old_disc is None:
            # This is new, so create it from the basic TOC we
            # got from mb2_disc
            disc = new_disc
            self.log('ripping new disc: {}', disc)
            self.db.create_disc(disc)
            self.tasks = [self.rip_audio, self.rip_toc]
        else:
            disc = old_disc

            if not disc.rip:
                # Ripped with older method, so replace offsets
                # with the ones from the basic TOC

                self.log('re-ripping {}', disc)
                toc.merge_basic_toc(disc, new_disc)
                self.db.save_disc_info(disc)
                self.tasks = [self.rip_audio, self.rip_toc]

            elif not disc.toc:
                # Audio ripped, but stopped before toc
                self.log('restarting TOC rip for {}', disc)
                self.tasks = [self.rip_toc]

            # otherwise all ripped, nothing to do

        self.disc = disc
        self.db_id = db_id
        self.state.disc_id = disc.disc_id

        return disc


    def tick(self):
        """Called by the main process to check on ripping progress.
        The ripper returns True as long as it is still running.
        """

        try:
            if not self.current_task:
                if not self.tasks:
                    # All done, stop process
                    if self.state.state != RipState.INACTIVE:
                        self.state = RipState()
                        self.update_state()
                    return False

                self.current_task = self.tasks[0]()
                del self.tasks[0]

            self.current_task.next()
            return True

        except StopIteration:
            # Task done, call ourselves recursively to trigger next task if any
            self.current_task = None
            return self.tick()

        # Propagate errors to clients and tell player we've given up
        except RipError, e:
            self.log('rip failed: {0}', e)
            self.state.error = str(e)
            self.update_state()
            return False


    def stop(self):
        """Stop the ripping process, abandoning any uncompleted processes.
        """
        # Drop any pending tasks
        self.tasks = []
        if self.current_process:
            self.log('killing rip process {} on stop from player',
                     self.current_process.pid)
            self.current_process.terminate()

        while self.tick():
            time.sleep(1)


    def rip_audio(self):
        self.log('ripping audio for disc: {0}', self.disc)

        audio_path = self.db.get_audio_path(self.db_id)

        # A span of -NUM_TRACKS forces cdparanoia to read everything, including
        # hidden tracks before the first proper track
        span = '-{}'.format(len(self.disc.tracks))

        args = [self.cfg.cdparanoia_command,
                '--force-cdrom-device', self.cfg.cdrom_device,
                '--output-raw-big-endian']

        if self.cfg.cdrom_read_speed:
            args += ['--force-read-speed', str(self.cfg.cdrom_read_speed)]

        args += ['--', span, audio_path]

        audio_process = self.run_process(args, 'rip_audio.log')
        audio_size = self.disc.get_disc_file_size_bytes()
        assert audio_size > 0

        self.state.state = RipState.AUDIO
        self.state.progress = 0
        self.update_state()

        while True:
            rc = audio_process.poll()
            if rc is None:
                # Still in progress, just check how far into the disc it is
                try:
                    stat = os.stat(audio_path)
                    progress = int(100 * (float(stat.st_size) / audio_size))
                except OSError:
                    progress = 0

                if progress != self.state.progress:
                    self.state.progress = progress
                    self.update_state(log_state = False)

                # Keep going
                yield
            else:
                break

        self.debug('audio ripping process finished with status {0}', rc)
        if rc != 0:
            raise RipError('audio ripping failed: status {0}'.format(rc))


        try:
            # Reload disc object, since it might have changed while ripping
            disc = self.db.get_disc_by_db_id(self.db_id)
            if not disc:
                raise RipError('disc missing after ripping in database: {}'.format(self.db_id))

            disc.rip = True
            self.db.save_disc_info(disc)
            self.disc = disc
        except db.DatabaseError, e:
            raise RipError('error updating rip flag: {0}'.format(e))


    def rip_toc(self):
        self.log('reading full TOC for disc: {0}', self.disc)

        toc_path = self.db.get_orig_toc_path(self.db_id)

        # In case an old TOC file exists, remove it first
        # since cdrdao refuses to overwrite it
        try:
            os.unlink(toc_path)
        except OSError:
            pass

        # Build the command line
        args = [self.cfg.cdrdao_command,
                'read-toc',
                '--device', self.cfg.cdrom_device,
                '--datafile', self.db.get_audio_file(self.db_id),
                toc_path]

        toc_process = self.run_process(args, 'rip_toc.log')

        self.state.state = RipState.TOC
        self.state.progress = None
        self.update_state()

        while True:
            rc = toc_process.poll()
            if rc is None:
                # Still in progress, keep going
                yield
            else:
                break

        self.debug('TOC reading process finished with status {0}', rc)
        if rc != 0:
            raise RipError('toc ripping failed: status {0}'.format(rc))

        try:
            # Merge full TOC into existing disc object
            toc_disc = toc.read_toc(toc_path, self.disc.disc_id)
        except toc.TOCError as e:
            raise RipError('error reading TOC: {0}'.format(e))

        try:
            # Reload disc object, since it might have changed while ripping
            disc = self.db.get_disc_by_db_id(self.db_id)
            if not disc:
                raise RipError('disc missing after TOC ripping in database: {}'.format(self.db_id))

            toc.merge_full_toc(disc, toc_disc)
            disc.toc = True

            self.db.save_disc_info(disc)
            self.disc = disc
        except db.DatabaseError, e:
            raise RipError('error updating rip flag: {0}'.format(e))


    def run_process(self, args, log_file_name):
        path = self.db.get_disc_dir(self.db_id)
        try:
            log_path = os.path.join(path, log_file_name)
            log_file = open(log_path, 'wt')
        except IOError, e:
            raise RipError("error ripping disc: can't open log file {0}: {1}"
                           .format(log_path, e))

        self.debug('executing command in {0}: {1!r}', path, args)

        try:
            self.current_process = subprocess.Popen(
                args,
                cwd = path,
                close_fds = True,
                stdout = log_file,
                stderr = subprocess.STDOUT)
            return self.current_process
        except OSError, e:
            raise RipError("error executing command {0!r}: {1}".format(args, e))


    def update_state(self, log_state = True):
        if log_state:
            self.debug('state: {0}', self.state)

        for p in self.publishers:
            p.update_rip_state(self.state)
