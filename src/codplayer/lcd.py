# codplayer - LCD display interfaces
#
# Copyright 2013-2015 Peter Liljenberg <peter.liljenberg@gmail.com>
#
# Distributed under an MIT license, please see LICENSE in the top dir.

#
# Interfaces used for the configuration objects
#

import sys

from . import zerohub
from . import state
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

    def format(self, state, rip_state, disc):
        """Format the current player state into a string
        that can be sent to the LCD display.

        Each line should be separated by a newline character,
        but there should not be any trailing newline.

        It is up to the LCD controller class to do any optimisations
        to reduce the amount of screen that is redrawn, if applicable.

        Instead of returning a string, the method can return a
        (string, time_t) pair.  The time_t indicates how long the
        display string is valid, and requests that format() should be
        called again at this time even if no state have changed.

        state and rip_state can only be null at startup before the
        state have been received from the player.

        If disc is non-null, it corresponds to the disc currently
        loaded so the formatter does not need to check that.
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
            state_receiver = state.StateClient(
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

        msg = self._cfg.formatter.format(self._state, self._rip_state, disc)
        if type(msg) == type(()):
            msg, timeout = msg
            self._io_loop.add_timeout(timeout, self._update)

        self._lcd_controller.home()
        self._lcd_controller.message(msg)



#
# Formatters
#

class LCDFormatterBase(ILCDFormatter):
    PLAY = '\x10'
    PAUSE = '\x60'
    STOP = ' ' # TODO: should upload a stop symbol in CGRAM
    WORKING = '-/|\\'

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


    def format(self, state, rip_state, disc):
        if state is None:
            return self.fill(
                full_version(),
                'Waiting on state')

        # TODO: do this properly

        line1 = '{0.state.__name__} {0.track}/{0.no_tracks} {0.position}/{0.length}'.format(state)
        line2 = disc.disc_id if disc else ''
        return self.fill(line1, line2)



class LCDFormatter16x2(LCDFormatterBase):
    COLUMNS = 16
    LINES = 2


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
