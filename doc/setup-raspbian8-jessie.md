codplayer setup on Raspbian 8 (Jessie)
======================================

The following steps sets up a plain Raspbian Jessie to run codplayer
with a USB DAC, WIFI network and accessing the disc database over NFS.

*Note: this was written quite some time after the fact, so it's
possible some details are missing or wrong.*


General system setup
--------------------

This assumes that a standard Raspbian has already been installed and
is running.

If the system no longer boots properly after one of the steps, you can
always mount the SD card in a Linux box and try to fix the botched
files.

### Disable CPU low-power modes

Force performance CPU scaling by adding this line to `/etc/rc.local`
(before any `exit 0`):

    echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

### Setup NFS

Install the necessary daemons:

    sudo apt-get install nfs-common rpcbind

Add the mountpoints to '/etc/fstab` (do not remove any existing lines, and change server names and paths to match your system):

    my.nfs.server:/data/music/coddb /mnt/coddb nfs noatime,rw,nodev,nosuid 0 0

systemd has borked NFS mounting, so start the services and mount the
directory in `/etc/rc.local`:

    service rpcbind start
    service nfs-common start
    mount -a -t nfs


### Disable hourly cron jobs

To avoid hourly cron jobs messing with playback, change `/etc/crontab` to make them daily:

```
# m h dom mon dow user	command
17 5	* * *	root    cd / && run-parts --report /etc/cron.hourly
25 5	* * *	root	test -x /usr/sbin/anacron || ( cd / && run-parts --report /etc/cron.daily )
47 5	* * 7	root	test -x /usr/sbin/anacron || ( cd / && run-parts --report /etc/cron.weekly )
52 5	1 * *	root	test -x /usr/sbin/anacron || ( cd / && run-parts --report /etc/cron.monthly )
```


Sound-specific setup
--------------------

Ensure that the DAC is always ALSA card 0.  Create the file
`/etc/modprobe.d/usb-dac.conf` with this line:

    options snd slots=snd-usb-audio
    options snd-usb-audio index=0
    
Edit `/etc/asound.conf` to set the default card to the USB card:

    pcm.0 { type hw; card 0; }
    ctl.0 { type hw; card 0; }
    pcm.!default pcm.0
    ctl.!default ctl.0


LCD/IR-specific setup
---------------------

If you intend to use the codlcd or codlircd daemons, additional
packages are needed:

    apt-get install python-smbus lirc

Add this line to `/boot/config.txt` to activate the lirc kernel
module, listening on the GPIO pins used by the control board:

    dtoverlay=lirc-rpi,gpio_out_pin=8,gpio_in_pin=4

Use these settings in `/etc/lirc/hardware.conf`:

    DRIVER="default"
    DEVICE="/dev/lirc0"
    MODULES="lirc_rpi"

Install a `/etc/lirc/lircd.conf` that matches your remote.  A config
file for Cyrus Commander is available at
https://github.com/petli/codplayer/blob/master/etc/lirc/cyrus-commander.conf


codplayer setup
---------------

Create a group and a user to run the codplayer daemons and give them
access to the necessary hardware.  Make sure to create the same group
and user on the NFS server with the same GID/UID and give them
ownership of the disc database directory.

    groupadd -g 586 cod
    useradd -u 586 -g cod -G cdrom,audio,gpio cod

Following the steps in `INSTALL.md` to install all dependencies and
install codplayer in a virtualenv with pip.  This example uses a
virtualenv in `/opt/cod`, which means that the configuration files are
in `/opt/cod/local/etc`.

In addition to the other configuration, use the created accounts in
the setup for `codplayer.conf` and `codlircd.conf`:

    user = 'cod'
    group = 'cod'
    initgroups = True

(`codlcd` must run as root.)

copy `tools/on_cd*.sh-systemd` to `/usr/local/bin`, dropping the
`-systemd` suffix and set the executable flag on them.

Copy `etc/udev/rules.d/99-codplayer.rules-systemd` script to
`/etc/udev/rules.d/99-codplayer.rules` to trigger playback when a CD
is inserted.  This also requires that `codctl` is found in `PATH`,
easiest with a symlink:

    sudo ln -s /opt/cod/bin/codctl /usr/local/bin/codctl

Start codplayer and the optional LCD and IR deamons by adding these
lines to `/etc/rc.local` (before any `exit 0` line):

    mkdir /var/run/codplayer
    chown cod.cod /var/run/codplayer
    
    /opt/cod/bin/codlcd
    /opt/cod/bin/codlircd
    /opt/cod/bin/codplayerd

Since codplayer logs a bit and continuously updates state files, these
are stored in ramdisk on /var/run to avoid wearing out the SD card
with writes.  Since it's a ramdisk, the dir must be setup on each
boot.


## Testing the setup

Run `/opt/cod/bin/codplayerd -d` to run codplayer without forking it as a
background daemon.  See if it logs any errors.  This line is OK if the
USB DAC isn't connected yet:

    c_alsa_sink: error opening card: No such file or directory
