
codplayer database admin GUI
============================

The admin GUI makes it possible to update information about the discs
in the database, either manually or by fetching it from
[MusicBrainz](http://musicbrainz.org/).

It can also control playback of discs to force tracks to be skipped or
to pause the player between certain tracks.  Discs can be linked to
other discs as aliases, so that playing one disc really plays another
one.

It is also possible to play discs directly from the GUI in one or more
player instances.

The admin GUI is provided by `codrestd`.


Typical use case
----------------

1. After inserting a new disc, go to "Discs without info"
2. Click on the disc to open up the details
3. If necessary, click on the play button to be reminded
   which album it is
4. Try to fetch info from MusicBrainz
5. If that fails or is incorrect, edit it manually
6. Add any edits to the track list
7. Save the updated disc info


Main view
---------

There are three tabs, all showing list of discs in the database,
depending on whether they have any disc information added or not.

Each disc is a row, including the artist, title and number of tracks.
A link icon is included if the disk is an alias for another disc.

The lists are sorted in this order:

1. Album artist (excluding any "The" prefix)
2. Date
3. Album title

This achieves an major alphabetical sort by artist, and chronological
within the artist.  Missing information is sorted last.

The lists in the three tabs are not updated or resorted as information
is changed.  This is partly out of lazyness on the part of the
programmer, but also to avoid confusing the user by moving things
around when hitting Save.  To refresh the lists, reload the page.


Disc details
------------

Click on a disc row to expand it to show the information about the
disc.

The track list:

* Shows Artist information only if it is different from the album
artist.
* Skipped tracks are listed in grey with an overstrike.
* A forced pause is shown as a pause symbol where it is inserted.

The MusicBrainz disc ID, barcode and catalog numbers (if known) are
shown below the track list.

If the disc is linked to another disc, the artist, title and disc ID
are displayed.


Edit disc details
-----------------

Click on `Edit` to change the disc display to edit mode.  More than one
disc can be edited at the same time.  Any unsaved changes are lost
if the page is reloaded.

There is no need to enter track artist information if it is the same
as the album artist.

Below the track numbers are two control buttons:

* Click on the crossed-out circle to skip this track when playing the
  disc
* Click on the pause symbol to insert a pause _after_ this track


Fetch information from MusicBrainz
----------------------------------

Click on `Fetch info` to fetch disc information from MusicBrainz.

If there is exactly one matching record, the disc display will switch
to edit mode with the fetched information filled in.  Click on `Save`
to accept it, optionally after making any edits, or `Cancel` to
discard it.

If more than one record matches, all will be displayed.  Click on one
of the records to select it and get to the edit view, or `Cancel` to
discard all.


Linking discs
-------------

Click on `Link` to open a menu to link this disc to another one.
Available options:

* `As alias for another disc`: when this disc is placed in the CD
  reader, the linked disc is played instead.  An example usecase is to
  play a remastered CD when inserting the original release.

The target disc is selected in a modal dialog.  Click on a disc to
link to it, or cancel by clicking the `Cancel` button, press `Escape`,
or click outside the dialog.

If the disc is linked, the menu also has an option `Remove link to the
other disc`.


Play discs
----------

If `codrestd` has been configured with one or more web control widget
instances, they will be listed in the lower right corner.  Each
contains the configured name of the player and a summary of the
current state, if it is currently playing a disc.

Click on the widget to expand it to show the details of the player
state and allow further control.

When hovering over a disc row, the number of tracks change to a play
button which will play the disc as if it had been inserted into the
player physically.  If any disc is currently playing, it will be
replaced.

When more than one player is configured, the active player is
controlled by the radio buttons before the player names.
