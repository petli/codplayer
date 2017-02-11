// codplayer web admin GUI
//
// Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
//
// Distributed under an MIT license, please see LICENSE in the top dir.

/* global Backbone, $, _ */

$(function(){
    'use strict';

    //
    // Alerts
    //

    var showAlert = function(info) {
        var template = _.template($('#alert-template').html());
        $('#alert-area').append(template(info));
    };


    //
    // Disc model and collection
    //

    // Collection of all known discs
    var discs;

    var getSortKey = function(value) {
        if (value && typeof value === 'string') {
            value = value.toLowerCase();
            if (/^the /.test(value)) {
                value = value.slice(4);
            }
            return value;
        }
        // Force missing fields to be sorted last
        return '\uffff';
    };

    var Disc = Backbone.Model.extend({
        idAttribute: 'disc_id',

        initialize: function() {
            this.updateSortKey();
            this.listenTo(this, 'change', this.updateSortKey);
        },

        updateSortKey: function() {
            // Preconstruct a disc compare string to speed up sorting
            // Primary key: artist
            // Secondary key: year of release
            // Tertiary key: title
            // Fallback: disc ID (after anything with info

            this.sortKey = getSortKey(this.get('artist')) + '\0' +
                getSortKey(this.get('date')) + '\0' +
                getSortKey(this.get('title')) + '\0' +
                this.get('disc_id');
        },
    });

    var DiscList = Backbone.Collection.extend({
        model: Disc,

        url: 'discs',

        comparator: function(m) {
            return m.sortKey;
        }
    });

    //
    // Musicbrainz disc info model and collection
    //
    
    var MBDisc = Backbone.Model.extend({
        idAttribute: 'mb_id',
    });

    var MBDiscList = Backbone.Collection.extend({
        model: MBDisc,
    });

    //
    // Player instances
    //

    var Player = Backbone.Model.extend({
        initialize: function() {
            this.set('state', null);
            this.set('rip_state', null);
            this.set('selected', false);
        },
    });

    var PlayerList = Backbone.Collection.extend({
        url: 'players',
        model: Player,

        initialize: function() {
            var self = this;
            var url = location.protocol + '//' + location.host + '/client';

            this.stateClient = new SockJS(url);
            this.stateClient.onmessage = function(e) {
                var player = self.get(e.data.id);
                if (player) {
                    if (e.data.state) {
                        var state = e.data.state;

                        state.positionString = self.formatTime(state.position);
                        state.lengthString = self.formatTime(state.length);

                        player.set('state', state);
                    }

                    if (e.data.rip_state) {
                        player.set('rip_state', e.data.rip_state);
                    }
                }
            };
        },

        formatTime: function(seconds) {
            var sign = '';
            if (seconds < 0) {
                sign = '-';
                seconds = -seconds;
            }

            var minPart = Math.floor(seconds / 60).toString();
            var secPart = (seconds % 60).toString();

            if (secPart.length === 1) {
                secPart = '0' + secPart;
            }

            return sign + minPart + ':' + secPart;
        }
    });


    //
    // Disc selection popup
    //
    // Emits events disc-selected or cancelled.
    //

    var DiscSelectionView = Backbone.View.extend({
        events: {
            'hide.bs.modal': 'onHide',
            'hidden.bs.modal': 'onHidden',
            'click .disc-row': 'onDiscClick',
        },

        itemTemplate: _.template($('#disc-row-template').html()),

        show: function(title) {
            var self = this;

            $('#disc-selection-title').text(title);

            var $list = this.$('#disc-selection-list');

            $list.empty();
            discs.each(function(disc) {
                $list.append(self.itemTemplate(disc.toJSON()));
            });

            this.$el.modal('show');
        },

        onDiscClick: function(ev) {
            var disc_id = ev.currentTarget.dataset.discId;
            var disc = discs.get(disc_id);

            if (disc) {
                this.trigger('disc-selected', disc);
                this.$el.modal('hide');
            }
            else {
                console.error('unknown disc ID selected', disc_id);
            }
        },

        onHide: function() {
            this.trigger('cancelled');
        },

        onHidden: function() {
            this.$('#disc-selection-list').empty();
        },
    });

    var discSelectionView = new DiscSelectionView({
        el: $("#disc-selection").get(0),
    });


    //
    // List view of a disc.  This consists of a master view holding
    // the position in the list of discs, and a specialised view for
    // the kind of information displayed.
    //

    var DiscRowView = Backbone.View.extend({
        tagName: 'li',
        className: 'list-group-item disc',

        initialize: function() {
            this.discView = null;
            this.setView(new DiscOverView({ model: this.model }));
        },

        render: function() {
            this.discView.render();
            return this;
        },

        setView: function(view) {
            this.discView = view;
            this.listenTo(view, 'disc-view:overview', this.onOverView);
            this.listenTo(view, 'disc-view:details', this.onViewDetails);
            this.listenTo(view, 'disc-view:edit', this.onViewEdit);
            this.listenTo(view, 'disc-view:mbinfo', this.onViewMBInfo);
            this.el.appendChild(view.el);

            if (this.model.get('artist') || this.model.get('title')) {
                this.$el.addClass('disc-with-info');
                this.$el.removeClass('disc-without-info');
            }
            else {
                this.$el.addClass('disc-without-info');
                this.$el.removeClass('disc-with-info');
            }

            this.render();
        },

        dropView: function() {
            this.stopListening(this.discView);
            this.discView.remove();
            this.discView = null;
        },

        onOverView: function() {
            console.log('switching to: overview');
            this.dropView();
            this.setView(new DiscOverView({ model: this.model }));
        },

        onViewDetails: function() {
            console.log('switching to: details');
            this.dropView();
            this.setView(new DiscDetailsView({ model: this.model }));
        },

        onViewEdit: function(mbDisc) {
            console.log('switching to: edit');
            this.dropView();
            this.setView(new DiscEditView({ model: this.model, mbDisc: mbDisc }));
        },

        onViewMBInfo: function(mbDiscs) {
            console.log('switching to: info');
            this.dropView();
            this.setView(new DiscMBInfoView({ model: this.model, collection: mbDiscs }));
        },
    });

    var DiscViewBase = Backbone.View.extend({
        tagName: 'div',

        render: function() {
            var data = this.model.toJSON();

            // Resolve links to next disc to be able to render
            // its artist and title
            var linked_disc_id = this.model.get('linked_disc_id');
            data.linked_disc = linked_disc_id && discs.get(linked_disc_id);

            this.$el.html(this.template(data));
            return this;
        },

        formatTime: function(seconds) {
            var sign = '';
            if (seconds < 0) {
                sign = '-';
                seconds = -seconds;
            }

            var minPart = Math.floor(seconds / 60).toString();
            var secPart = (seconds % 60).toString();

            if (secPart.length === 1) {
                secPart = '0' + secPart;
            }

            return sign + minPart + ':' + secPart;
        },

        onCancel: function() {
            this.trigger('disc-view:details');
        },

        onPlayDisc: function() {
            Backbone.trigger('play-disc', this.model.get('disc_id'));
        },
    });


    var DiscOverView = DiscViewBase.extend({
        events: {
            'click .play-disc': 'onPlayDisc',
            'click .disc-row': 'onToggleDetails',
        },

        template: _.template($('#disc-row-template').html()),

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);
        },

        onToggleDetails: function(event) {
            var self = this;

            if (event.target.tagName.toUpperCase() === 'BUTTON') {
                /* Ignore clicks on the play button */
                return;
            }

            if (typeof this.model.get('tracks') === 'number') {
                // We only have the partial disc info, so fetch
                // the full structure
                
                // TODO: provide some feedback to the user here

                this.model.fetch({
                    success: function() {
                        self.trigger('disc-view:details');
                    },

                    error: function(model, response) {
                        showAlert({
                            header: 'Error fetching disc details:',
                            message: (response.statusText + ' (' + response.status +
                                      ') [' + model.get('disc_id') + ']'),
                        });
                    },
                });
            }
            else {
                self.trigger('disc-view:details');
            }
        },
    });


    var DiscDetailsView = DiscViewBase.extend({
        className: 'disc-details-view',

        events: {
            'click .play-disc': 'onPlayDisc',
            'click .toggle-details': 'onToggleDetails',
            'click .edit-disc': 'onStartEdit',
            'click .fetch-musicbrainz': 'onFetchMusicbrainz',
            'click .link-disc': 'onLinkDisc',
            'click .remove-link': 'onRemoveLink',
        },

        template: _.template($('#disc-row-template').html() +
                             $('#disc-detail-template').html()),

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);
        },

        onToggleDetails: function(event) {
            if (event.target.tagName.toUpperCase() === 'BUTTON') {
                /* Ignore clicks on the play button */
                return;
            }

            this.trigger('disc-view:overview');
        },

        onStartEdit: function() {
            this.trigger('disc-view:edit');
        },

        onFetchMusicbrainz: function() {
            var mbDiscs;
            var self = this;
            
            mbDiscs = new MBDiscList();
            mbDiscs.url = this.model.url() + '/musicbrainz';

            // Disable all buttons before we do anything else and
            // provide feedback in the button
            this.$('fieldset').prop('disabled', true);
            this.$('.fetch-musicbrainz').button('loading');

            mbDiscs.fetch({
                success: function(collection) {
                    self.fetchMusicbrainzSuccess(collection);
                },

                error: function(collection, response) {
                    self.fetchMusicbrainzError(response);
                },
            });
        },

        fetchMusicbrainzSuccess: function(mbDiscs) {
            this.$('.fetch-musicbrainz').button('reset');
            this.$('fieldset').prop('disabled', false);

            if (mbDiscs.length === 0) {
                // This should be a 404, but handle it in any case
                showAlert({
                    header: 'Sorry,',
                    message: 'Musicbrainz has no information about this disc. [' + this.model.get('disc_id') + ']',
                });
            }
            else if (mbDiscs.length === 1) {
                this.trigger('disc-view:edit', mbDiscs.at(0));
            }
            else {
                this.trigger('disc-view:mbinfo', mbDiscs);
            }
        },

        fetchMusicbrainzError: function(response) {
            this.$('.fetch-musicbrainz').button('reset');
            this.$('fieldset').prop('disabled', false);

            if (response.status === 404) {
                showAlert({
                    header: 'Sorry,',
                    message: 'Musicbrainz has no information about this disc. [' + this.model.get('disc_id') + ']',
                });
            }
            else {
                showAlert({
                    header: 'Error fetching info:',
                    message: response.statusText + ' (' + response.status + ') [' + this.model.get('disc_id') + ']',
                });
            }
        },

        onLinkDisc: function(event) {
            var $target = $(event.target);

            this.listenTo(discSelectionView, 'disc-selected', function(disc) {
                this.stopListening(discSelectionView);
                if (disc) {
                    this.model.save({
                        link_type: $target.data('type'),
                        linked_disc_id: disc.get('disc_id'),
                    });
                }
		// Since this disc might have been scrolled away when
		// browsing the selection modal
		this.el.scrollIntoView();
            });

            this.listenTo(discSelectionView, 'cancelled', function() {
                this.stopListening(discSelectionView);
		this.el.scrollIntoView();
            });

            discSelectionView.show($target.data('title'));
        },

        onRemoveLink: function() {
            this.model.save({
                link_type: null,
                linked_disc_id: null,
            });
        },
    });

    var DiscEditView = DiscViewBase.extend({
        events: {
            'click .save-edit': 'onSaveEdit',
            'click .cancel-edit': 'onCancel',
        },

        
        template: _.template($('#disc-edit-template').html()),

        initialize: function(options) {
            var mbTracks, modelTracks;
            
            this.mbDisc = options.mbDisc;

            if (this.mbDisc) {
                // Ensure this has the right number of tracks

                mbTracks = this.mbDisc.get('tracks');
                modelTracks = this.model.get('tracks');

                // If there are an initial hidden track and that
                // doesn't seem to be in the MB response, push it to
                // the front
                if (modelTracks[0].number === 0 &&
                    modelTracks.length > mbTracks.length) {
                    mbTracks.unshift(modelTracks[0]);
                }

                // Add track info at the end, if missing in MB response
                while (mbTracks.length < modelTracks.length) {
                    mbTracks.push(_.clone(modelTracks[mbTracks.length]));
                }

                // Trim MB response, if longer than the local disc
                while (mbTracks.length > modelTracks.length) {
                    mbTracks.pop();
                }

                // Copy over information not in the MB response

                var discProps = [ 'catalog', 'title', 'artist', 'barcode', 'date' ];
                var trackProps = [ 'isrc', 'title', 'artist', 'skip', 'pause_after' ];
                var i, n, prop;

                for (i = 0; i < discProps.length; i++) {
                    prop = discProps[i];
                    if (!this.mbDisc.get(prop)) {
                        this.mbDisc.set(prop, this.model.get(prop));
                    }
                }

                for (n = 0; n < mbTracks.length; n++) {
                    for (i = 0; i < trackProps.length; i++) {
                        prop = trackProps[i];
                        if (!mbTracks[n][prop]) {
                            mbTracks[n][prop] = modelTracks[n][prop];
                        }
                    }
                }
            }
        },

        render: function() {
            var model = this.mbDisc || this.model;

            this.$el.html(this.template(model.toJSON()));
            return this;
        },

        onSaveEdit: function() {
            // Get the values of the edit fields.  Put them all into a
            // map so we can call model.save() and have them all
            // stashed to the server atomically(ish)

            var self = this;
            var save = {};

            var getTrackValues = function(field, func) {
                self.$('[data-edit-field="' + field + '"]').each(function(elementIndex, element) {
                    var i = parseInt(element.dataset.editTrackIndex, 10);
                    
                    if (!_.isNaN(i) && i >= 0 && i < save.tracks.length) {
                        func(save.tracks[i], element);
                    }
                    else {
                        console.error('Bad data-edit-track-index: ' + element.dataset.editTrackIndex);
                    }
                });
            };

            // Disable the forms before we do anything else
            this.$('fieldset').prop('disabled', true);

            // We need a deep copy of the track array
            save.tracks = _.map(this.model.get('tracks'), _.clone);

            save.artist = this.$('[data-edit-field="disc-artist"]').val();
            save.title = this.$('[data-edit-field="disc-title"]').val();
            save.date = this.$('[data-edit-field="date"]').val();

            getTrackValues('track-artist', function(track, element) {
                track.artist = element.value;
            });

            getTrackValues('track-title', function(track, element) {
                track.title = element.value;
            });

            getTrackValues('track-skip', function(track, element) {
                track.skip = $(element).hasClass('active');
            });

            getTrackValues('track-pause-after', function(track, element) {
                track.pause_after = $(element).hasClass('active');
            });


            // If we got this from a mbDisc, copy the fields that are
            // not visible in the GUI
            if (this.mbDisc) {
                save = _.extend(save, this.mbDisc.pick(
                    'mb_id', 'cover_mb_id',

                    // These two should really be moved into the GUI:
                    'catalog', 'barcode'));
            }

            // Do save, but don't update model until we get a response
            // from server.  Also set editing mode to false so that a
            // successful update renders the viewing mode directly.
            
            this.model.save(save, {
                wait: true,

                success: function() {
                    self.trigger('disc-view:details');
                },

                error: function(model, xhr) {
                    // Unlock fields so the user can cancel or retry save
                    self.$('fieldset').prop('disabled', false);

                    showAlert({
                        header: 'Error saving changes:',
                        message: (xhr.statusText + ' (' + xhr.status +
                                  ') [' + self.model.get('disc_id') + ']'),
                    });
                },
            });
        },
    });

    var DiscMBInfoView = DiscViewBase.extend({
        events: {
            'click .cancel-mbinfo': 'onCancel',
        },
        
        template: _.template($('#disc-mbinfo-template').html()),

        render: function() {
            var self = this;
            var row = null;
            
            this.$el.html(this.template(this.model.toJSON()));
            this.collection.each(function(model) {
                var view = new MBDiscView({ model: model });
                self.listenTo(view, 'disc-view:edit', self.onSelect);

                if (row === null) {
                    row = $('<div class="row mb-disc-row">');
                    self.$('div.mb-discs').append(row);
                    row.append(view.render().el);
                } else
                {
                    row.append(view.render().el);
                    row = null;
                }
            });

            return this;
        },

        onSelect: function(mbDisc) {
            this.trigger('disc-view:edit', mbDisc);
        },
    });


    var MBDiscView = DiscViewBase.extend({
        className: 'mb-disc col-xs-12 col-md-6 hover-row',
        
        events: {
            'click': 'onSelect',
        },
        
        template: _.template($('#mbdisc-template').html()),

        onSelect: function() {
            this.trigger('disc-view:edit', this.model);
        },
    });


    //
    // List view of all discs
    //

    var DiscsView = Backbone.View.extend({
        el: $('#discs'),

        events: {
            'click #show-all-discs': 'onShowAllDiscs',
            'click #show-discs-with-info': 'onShowDiscsWithInfo',
            'click #show-discs-without-info': 'onShowDiscsWithoutInfo',
        },

        initialize: function() {
            this.discList = this.$('#disc-list');
        },

        render: function() {
            var self = this;

            this.discList.hide();
            this.discList.empty();
            this.collection.each(function(disc) {
                var view = new DiscRowView({ model: disc });
                self.discList.append(view.render().el);
            });
            this.discList.fadeIn();
        },

        onShowAllDiscs: function() {
            this.$('.nav .active').removeClass('active');
            this.$('#show-all-discs').addClass('active');
            this.discList.find('.disc').show();
        },

        onShowDiscsWithInfo: function() {
            this.$('.nav .active').removeClass('active');
            this.$('#show-discs-with-info').addClass('active');
            this.discList.find('.disc-without-info').hide();
            this.discList.find('.disc-with-info').show();
        },

        onShowDiscsWithoutInfo: function() {
            this.$('.nav .active').removeClass('active');
            this.$('#show-discs-without-info').addClass('active');
            this.discList.find('.disc-with-info').hide();
            this.discList.find('.disc-without-info').show();
        },
    });


    //
    // Player views
    //

    var PlayerView = Backbone.View.extend({
        tagName: 'div',

        events: {
            'changed input.active-player': 'onSelectedChanged',
        },

        initialize: function() {
            this.activeRadio = null;
            this.listenTo(this.model, 'change', this.render);
            this.listenTo(Backbone, 'play-disc', this.onPlayDisc);
        },

        template: _.template($('#player-template').html()),

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            this.activeRadio = this.$('input.active-player');
            return this;
        },

        onSelectedChanged: function() {
            if (this.activeRadio) {
                this.model.set('selected', this.activeRadio.prop('checked'));
            }
        },

        onPlayDisc: function(discID) {
            if (!this.model.get('selected')) {
                return;
            }
        },
    });

    var PlayersView = Backbone.View.extend({
        el: $('#players'),

        render: function() {
            var self = this;

            this.$el.hide();
            this.$el.empty();
            this.collection.each(function(player) {
                var view = new PlayerView({ model: player });
                self.$el.append(view.render().el);
            });
            this.$el.fadeIn();
        },
    });


    //
    // Kick everything off by fetching the list of discs and the players
    //

    discs = new DiscList();
    var discsView;

    // TODO: provide progress report on this
    discs.fetch({
        success: function(collection) {
            discsView = new DiscsView({ collection: collection });
            discsView.render();
        }
    });

    var players = new PlayerList();
    var playersView;

    players.fetch({
        success: function(collection) {
            var firstPlayer = collection.first();
            if (firstPlayer) {
                firstPlayer.set('selected', true);
            }

            playersView = new PlayersView({ collection: collection });
            playersView.render();
        }
    });
});
