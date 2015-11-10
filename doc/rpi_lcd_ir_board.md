
LCD/IR board for RPi
====================

This board provide three UI functions:

* LCD display (16x2 or 20x4)
* Status LED
* IR reciever for remote control

In addition it is connected to a potentiometer that controls the LCD
contrast.

The IR reciever is handled by the RPi lirc kernel driver, and the
button presses are read and forwarded using ZeroMQ by `codird`.

The LCD display and status LED are controlled by `codlcd`, which
recieve button presses and status updates over ZeroMQ.

Board layout
------------

A full-sized AdaFruit RPi perma-proto board is used.

There are five connectors on the board:

* LCD: 2 6-pin connectors
* LCD contrast pot: 3-pin
* IR sensor: 3-pin
* Status LED: 2-pin

The other components are:

* R1:  10K
* R2: 150
* R3: 150
* R4: 470
* R5:   1K
* R6: 100
* Q1, Q2: PN2222A (or similar NPN)
* U1: opamp TLV2462 (or similar)

Off-board there are additional components which are situated in the
front of the chassis, connected via cables:

* Red LED (forward voltage about 2.1V)
* IR reciever: TSOP38238
* Potentiometer: 10k or more
* LCD: HD44780 compatible


GPIO pinout
-----------

Input:

* GPIO 4 (GLKC/GEN7): IR reciever

Output:

* GPIO 7 (CE1): Status LED
* GPIO 17 (GEN0): LCD RS (pin 4)
* GPIO 18 (GEN1): LCD backlight PWM control
* GPIO 22 (GEN3): LCD DB4 (pin 11)
* GPIO 23 (GEN4): LCD DB5 (pin 12)
* GPIO 24 (GEN5): LCD DB6 (pin 13)
* GPIO 25 (GEN6): LCD DB7 (pin 14)
* GPIO 21/27 (GEN2): LCD E/clock enable (pin 6)

Unused output:

* GPIO 8 (CE0): IR transmitter (not used, but the lircd kernel driver
  needs to grab a pin for it anyway)

Design considerations
---------------------

I don't know much of electronics, except what I've read on
http://www.electronics-tutorials.ws/ so this thing might be a bit
clumsy.  This is how I've thought, anyway:

Status LED and LCD backlight should get power from the 5V rail.  While
they could potentially be sinked into a GPIO output port, and some
examples show that
(e.g. https://learn.adafruit.com/character-lcd-with-raspberry-pi-or-beaglebone-black/wiring)
it feels a bit iffy since those ports only take 3.3V and limited
currents in.  Instead those two GPIO ports are connected to a plain
NPN transistor that is used as a switch, sinking the on currents into
the ground rail instead.

The LCD backlight I've got seems to consume some 60mA at 5V, but let's
assume 100mA to get some margin.  1 mA base current should be enough
to switch that on, even assuming a beta of 100 (more likely it is
200).  The 1K resistor R5 here ensures that no more than 2 mA is taken
from the RPi, even if the output is configured for more.

The status LED should get 20mA with a voltage drop of 2.1 V, which R2
controls.  R3 limits base current to the 200 uA or so that's needed.

It seems that the LCD contrast pin has a useful range of about 0-1.5V,
with the highest contrast at 0 V and at 1.5V barely anything is
visible.  To complicate things further, there seems to be a pullup
resistor of 10K on the LCD board, so just connecting a voltage
splitting potentiometer doesn't work: half of it ends up in a parallel
resistor network with the pullup.  Instead an opamp (U1) is used in a
simple voltage following configuration to isolate the potentiometer
from the pullup resistor.  The output voltage is split by R3 and R4,
so that 5V out from U1 gives ~1.5V on the contrast pin, which is the
lowest meaningful contrast.
