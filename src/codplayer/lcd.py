# codplayer - LCD display interfaces
#
# Copyright 2013-2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

#
# Interfaces used for the configuration objects
#

import sys
import time

from . import zerohub
from .state import State, RipState, StateClient
from . import command
from .codaemon import Daemon, DaemonError
from . import full_version

#
# Config object interfaces
#

class ILCDFactory(object):
    """Interface for LCD/LED controller factory classes.
    """
    def get_lcd_controller(self, columns, lines):
        """Create a LCD controller."""
        raise NotImplementedError()

    def get_led_controller(self):
        """Create a LED controller."""
        raise NotImplementedError()


class ILCDFormatter(object):
    """Interface for LCD formatter classes.

    Each class formats for a particular screen size, defined by
    COLUMNS and LINES.
    """

    COLUMNS = None
    LINES = None

    def format(self, state, rip_state, disc, now):
        """Format the current player state into a string
        that can be sent to the LCD display.

        Each line should be separated by a newline character,
        but there should not be any trailing newline.

        It is up to the LCD controller class to do any optimisations
        to reduce the amount of screen that is redrawn, if applicable.

        The method shall return a (string, time_t) pair.  The time_t
        indicates how long the display string is valid, and requests
        that format() should be called again at this time even if no
        state have changed.  If the time_t is None, then the display
        string should not be updated until the next state change.

        state and rip_state can only be null at startup before the
        state have been received from the player.

        If disc is non-null, it corresponds to the disc currently
        loaded so the formatter does not need to check that.

        now is the current time.time(), as considered by the LCD
        display.  The formatter should use this rather than
        time.time() directly to determine if the display should
        change.
        """
        raise NotImplementedError()


#
# LCD (and LED) main daemon
#

class LCD(Daemon):
    def __init__(self, cfg, mq_cfg, debug = False):
        self._cfg = cfg
        self._mq_cfg = mq_cfg

        self._state = None
        self._rip_state = None
        self._disc = None

        # Kick off deamon
        super(LCD, self).__init__(cfg, debug = debug)


    def setup_postfork(self):
        self._lcd_controller = self._cfg.lcd_factory.get_lcd_controller(
            self._cfg.formatter.COLUMNS, self._cfg.formatter.LINES)
        self._led_controller = self._cfg.lcd_factory.get_led_controller()

        self._io_loop = zerohub.IOLoop.instance()


    def run(self):
        try:
            # Set up initial message
            self._lcd_controller.clear()
            self._update()

            # Set up subscriptions on relevant state updates
            state_receiver = StateClient(
                channel = self._mq_cfg.state,
                io_loop = self._io_loop,
                on_state = self._on_state,
                on_rip_state = self._on_rip_state,
                on_disc = self._on_disc
            )

            # Kickstart things by requesting the current state from the player
            rpc_client = command.AsyncCommandRPCClient(
                zerohub.AsyncRPCClient(
                    channel = self._mq_cfg.player_rpc,
                    name = 'codlcd',
                    io_loop = self._io_loop))

            rpc_client.call('source', on_response = self._on_disc)
            rpc_client.call('state', on_response = self._on_state)
            rpc_client.call('rip_state', on_response = self._on_rip_state)

            # Let the IO loop take care of the rest
            self._io_loop.start()

        finally:
            # Turn off LED and clear display on exit to tell user that
            # there's no LED/LCD control anymore
            self._lcd_controller.clear()
            self._led_controller.off()


    def _on_state(self, state):
        self._state = state
        self._update()
        self.debug('got state: {}', self._state)


    def _on_rip_state(self, rip_state):
        self._rip_state = rip_state
        self._update()
        self.debug('got rip state: {}', self._rip_state)


    def _on_disc(self, disc):
        self._disc = disc
        self._update()
        self.debug('got disc: {}', self._disc)


    def _update(self):
        # Only pass the formatter a disc object relevant to the state
        if self._state and self._disc and self._state.disc_id == self._disc.disc_id:
            disc = self._disc
        else:
            disc = None

        now = time.time()
        msg, timeout = self._cfg.formatter.format(self._state, self._rip_state, disc, now)
        if timeout is not None:
            self._io_loop.add_timeout(timeout, self._update)

        self._lcd_controller.home()
        self._lcd_controller.message(msg)



#
# Formatters
#

class LCDFormatterBase(ILCDFormatter):
    """Base class for LCD formatters of different sizes."""

    COLUMNS = None
    LINES = None

    PLAY = '\x10'
    PAUSE = '\x60'
    UNKNOWN_STATE = '?'

    # Seconds between each scroll update
    SCROLL_SPEED = 0.3

    # Seconds scrolled text remains at end position
    SCROLL_PAUSE = 1

    def __init__(self):
        self._state = None
        self._rip_state = None
        self._disc = None
        self._current_track_number = 0
        self._info_generator = None
        self._info_lines = ''
        self._next_info_lines = None
        self._errors = None


    def fill(self, *lines):
        """Return a set of lines filled out to the full width and height of
        the display as a newline-separated string.
        """
        output_lines = []
        for line in lines:
            line = line[:self.COLUMNS]
            line = line + ' ' * (self.COLUMNS - len(line))
            output_lines.append(line)

        while len(output_lines) < self.LINES:
            output_lines.append(' ' * self.COLUMNS)

        return '\n'.join(output_lines[:self.LINES])


    def scroll(self, text, now, prefix = '', columns = None, loop = False):
        """Iterator that scrolls through text if necessary to fit
        within the line length.
        """

        if columns is None:
            columns = self.COLUMNS

        columns -= len(prefix)

        if len(text) <= columns:
            # No need to scroll
            yield prefix + text, None

        else:
            while True:
                for i in range(len(text) - columns):
                    now += self.SCROLL_SPEED
                    yield prefix + text[i : i + columns], now

                # Show last position a little longer
                now += self.SCROLL_PAUSE
                yield prefix + text[-columns:], now

                if not loop:
                    # Switch back to first position and scroll no more
                    yield prefix + text[:columns], None
                    return


    def format(self, state, rip_state, disc, now):
        if state is None:
            return self.fill(
                full_version(),
                'Waiting on state'), None

        self._state = state
        self._rip_state = rip_state

        # Check if there are error messages
        errors = None
        if state and state.error:
            errors = [state.error]
        if rip_state and rip_state.error:
            if errors:
                errors.append(rip_state.error)
            else:
                errors = [rip_state.error]

        if errors:
            if self._errors != errors:
                self._errors = errors
                # Need new formatter
                self._info_generator = self.generate_error_lines(now)
                self._next_info_lines = now

        else:
            # No current errors, show disc info

            # Show new disc info lines when disc change, or
            # when coming back from error
            if self._disc is not disc or self._errors:
                self._errors = None
                if disc is None:
                    self._disc = None
                    self._current_track_number = 0
                    self._info_generator = None
                    self._next_info_lines = None
                    self._info_lines = ''
                else:
                    self._disc = disc
                    self._current_track_number = state.track
                    self._info_generator = self.generate_disc_lines(now)
                    self._next_info_lines = now

            # Show new track info when switching track on a disc
            elif self._disc and self._current_track_number != state.track:
                self._current_track_number = state.track
                self._info_generator = self.generate_track_lines(now)
                self._next_info_lines = now

        # Update info line if there is still a generator
        # and the time has come
        while (self._info_generator is not None and
               self._next_info_lines is not None and
               now >= self._next_info_lines):
            try:
                self._info_lines, self._next_info_lines = self._info_generator.next()
            except StopIteration:
                # Keep the current info and stop generating new lines
                self._info_generator = None
                self._next_info_lines = None

        return self.do_format(), self._next_info_lines

    def do_format(self):
        raise NotImplementedError()

    def generate_disc_lines(self, now):
        """Return an iterator that provides information for a new disc.
        The generated values should be a tuple: (lines, next_update)

        This is not called if self._errors is non-empty.

        next_update is the unix time when the next value should be
        shown.  The final generated value should have next_update = None
        """
        raise NotImplementedError()

    def generate_track_lines(self, now):
        """Return an iterator that provides information for a new track.
        Behaves the same way as generate_disc_lines().

        This is not called if self._errors is non-empty.
        """
        raise NotImplementedError()

    def generate_error_lines(self, now):
        """Return an iterator that provides information for errors.
        Behaves the same way as generate_disc_lines().

        This is only called if self._errors is non-empty.
        """
        raise NotImplementedError()


class LCDFormatter16x2(LCDFormatterBase):
    """Format output for a 16x2 LCD display.

    See the TestLCDFormatter16x2 unit test for the expected
    output of this class for different player states.
    """

    COLUMNS = 16
    LINES = 2

    # Seconds that disc title and artist is kept visible
    DISC_INFO_SWITCH_SPEED = 3


    def scroll(self, text, now, prefix = '', loop = False):
        """Override to fit info line scroll into available space, which is
        shortened when ripping is in progress and should be shown at
        the end of the line.

        If ripping ends during the track this extra space will not be
        reclaimed until the next track starts.
        """

        scroll_columns = self.COLUMNS
        if self._rip_state and self._rip_state.state != RipState.INACTIVE:
            scroll_columns -= 4

        return super(LCDFormatter16x2, self).scroll(
            text, now, prefix = prefix, columns = scroll_columns, loop = loop)


    def do_format(self):
        return self.fill(
            self.do_format_state_line(),
            self.do_format_info_line())

    def do_format_state_line(self):
        s = self._state

        if s.state == State.NO_DISC:
            return 'No disc'

        elif s.state == State.STOP:
            return 'Stop {0.no_tracks:>4d} tracks'.format(s)

        elif s.state == State.WORKING:
            return 'Working {0.track:d}/{0.no_tracks:d}...'.format(s)

        else:
            if s.state == State.PLAY:
                state_char = self.PLAY
            elif s.state == State.PAUSE:
                state_char = self.PAUSE
            else:
                state_char = self.UNKNOWN_STATE

            if s.position < 0:
                # pregap
                track_pos = '-{0:d}:{1:02d}'.format(
                    abs(s.position) / 60, abs(s.position) % 60)
            else:
                # Regular position
                track_pos = ' {0:d}:{1:02d}'.format(
                    s.position / 60, s.position % 60)

            if s.length >= 600 and (s.track >= 10 or
                    (s.position >= 600 and s.no_tracks >= 10)):
                # Can only fit rough track length
                track_len = '{0:d}+'.format(s.length / 60)
            else:
                # Full track length will fit
                track_len = '{0:d}:{1:02d}'.format(
                    s.length / 60, s.length % 60)

            if s.length < 600:
                # Can give space to track numbers at left
                state_line = '{0}{1.track:>2d}/{1.no_tracks:<2d}{2}/{3}'.format(
                    state_char, s, track_pos, track_len)
            else:
                # Need to shift track numbers far to the left
                tracks = '{0}{1.track:d}/{1.no_tracks:d}'.format(state_char, s)
                pos = '{0}/{1}'.format(track_pos, track_len)
                fill = 16 - len(tracks) - len(pos)
                state_line = tracks + (' ' * fill) + pos

            return state_line


    def do_format_info_line(self):
        s = self._rip_state

        if s and s.state == RipState.AUDIO:
            if s.progress is not None:
                return '{0:<12s}{1:3d}%'.format(self._info_lines[:12], s.progress)
            else:
                return '{0:<12s} RIP'.format(self._info_lines[:12])
        elif s and s.state == RipState.TOC:
            return '{0:<12s} TOC'.format(self._info_lines[:12])
        else:
            return self._info_lines


    def generate_disc_lines(self, now):
        """Show album title and artist in sequence, then switch to track title.
        All are scrolled if necessary
        """

        disc_title = self._disc.title or 'Unknown album'
        for line, next_update in self.scroll(disc_title, now):
            if next_update is None:
                # Pause until switching to disc artist
                now += self.DISC_INFO_SWITCH_SPEED
                yield line, now
            else:
                now = next_update
                yield line, next_update

        disc_artist = self._disc.artist or 'Unknown artist'
        for line, next_update in self.scroll(disc_artist, now):
            if next_update is None:
                # Pause until switching to track title
                now += self.DISC_INFO_SWITCH_SPEED
                yield line, now
            else:
                now = next_update
                yield line, next_update

        for line, next_update in self.generate_track_lines(now):
            yield line, next_update


    def generate_track_lines(self, now):
        """Show track title, scrolled initially.
        """

        if self._state.track == 0:
            return self.scroll(self._disc.title or 'Unknown album', now)

        else:
            track_index = self._state.track - 1
            if track_index >= len(self._disc.tracks):
                return iter([('Bad track list!', None)])
            else:
                track = self._disc.tracks[track_index]
                track_title = track.title or 'Unknown track'
                if track.number != self._state.track:
                    # Track numbering is off, so show actual number here
                    prefix = '{}. '.format(track.number)
                else:
                    prefix = ''
                return self.scroll(track_title, now, prefix)

    def generate_error_lines(self, now):
        return self.scroll('; '.join(self._errors), now, loop = True)


#
# RPi GPIO interface
#

class GPIO_LCDFactory(ILCDFactory):
    def __init__(self, led,
                 rs, en, d4, d5, d6, d7,
                 backlight = None):
        self.pin_led = led
        self.pin_rs = rs
        self.pin_en = en
        self.pin_d4 = d4
        self.pin_d5 = d5
        self.pin_d6 = d6
        self.pin_d7 = d7
        self.pin_backlight = backlight

    def get_lcd_controller(self, columns, lines):
        from Adafruit_CharLCD import Adafruit_CharLCD
        return Adafruit_CharLCD(
            cols = columns,
            lines = lines,
            rs = self.pin_rs,
            en = self.pin_en,
            d4 = self.pin_d4,
            d5 = self.pin_d5,
            d6 = self.pin_d6,
            d7 = self.pin_d7,
            backlight = self.pin_backlight,
            invert_polarity = False,
        )

    def get_led_controller(self):
        import Adafruit_GPIO as GPIO
        return GPIO_LEDController(GPIO.get_platform_gpio(), self.pin_led)


class GPIO_LEDController(object):
    def __init__(self, gpio, pin):
        import Adafruit_GPIO as GPIO

        self.gpio = gpio
        self.pin = pin

        # Setup for output, and light up by default
        gpio.setup(pin, GPIO.OUT)
        self.on()

    def on(self):
        self.gpio.output(self.pin, 1)

    def off(self):
        self.gpio.output(self.pin, 0)


#
# Test classes for developing without the HW
#

class TestLCDFactory(ILCDFactory):
    def get_lcd_controller(self, columns, lines):
        return TestLCDController()

    def get_led_controller(self):
        return TestLEDController()


class TestLCDController(object):
    def __init__(self):
        self.enabled = True

    def home(self):
        self.clear()

    def clear(self):
        sys.stdout.write('\x1bc')
        sys.stdout.flush()

    def enable_display(self, enable):
        self.enabled = enable
        if not enable:
            self.clear()

    def message(self, text):
        text = text.replace(LCDFormatterBase.PLAY, '>')
        text = text.replace(LCDFormatterBase.PAUSE, '=')

        if self.enabled:
            sys.stdout.write(text)
            sys.stdout.write('\n')
            sys.stdout.flush()

    def set_backlight(self, backlight):
        pass


class TestLEDController(object):
    def on(self):
        sys.stdout.write('LED ON\n')
        sys.stdout.flush()

    def off(self):
        sys.stdout.write('LED OFF\n')
        sys.stdout.flush()
