// codplayer web admin GUI
//
// Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
//
// Distributed under an MIT license, please see LICENSE in the top dir.

$(function(){
    'use strict';

    //
    // Disc model and collection
    //
    
    var Disc = Backbone.Model.extend({
        idAttribute: 'disc_id',

        initialize: function() {
        },
    });

    // Sort empty/missing last, the rest in increasing order
    var discComparator = function(a, b, key) {
        a = a.get(key);
        b = b.get(key);

        if (a && b) {
            // Prepare both strings for comparison
            a = a.toLowerCase();
            b = b.toLowerCase();

            if (/^the /.test(a)) a = a.slice(4);
            if (/^the /.test(b)) b = b.slice(4);

            if (a < b) return -1;
            if (a > b) return 1
            return 0;
        }
        if (a) return -1;
        if (b) return 1;
        return 0;
    };

    var DiscList = Backbone.Collection.extend({
        model: Disc,

        url: 'discs',

        comparator: function(a, b) {
            // Primary key: artist
            // Secondary key: year of release
            // Tertiary key: title
            // Fallback: disc ID

            return (discComparator(a, b, 'artist') ||
                    discComparator(a, b, 'date') ||
                    discComparator(a, b, 'title') ||
                    discComparator(a, b, 'disc_id'));
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
    // Keep track of alerts
    //
    
    var Alert = Backbone.Model.extend({
        initialize: function() {
            this.set('header', null);
            this.set('message', null);
        },
    });

    var currentAlert = new Alert();
    
    //
    // Player instances
    //

    var Player = Backbone.Model.extend({
    });

    var PlayerList = Backbone.Collection.extend({
        url: 'players',
        model: Player,
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
            this.$el.html(this.template(this.model.toJSON()));
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

            if (secPart.length == 1) {
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
                        currentAlert.set({
                            header: 'Error fetching disc details:',
                            message: response.statusText + ' (' + response.status + ')',
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
        },

        template: _.template($('#disc-row-template').html()
                             + $('#disc-detail-template').html()),

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
                currentAlert.set({
                    header: 'Sorry,',
                    message: 'Musicbrainz has no information about this disc',
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
                currentAlert.set({
                    header: 'Sorry,',
                    message: 'Musicbrainz has no information about this disc',
                });
            }
            else {
                currentAlert.set({
                    header: 'Error fetching info:',
                    message: response.statusText + ' (' + response.status + ')',
                });
            }
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

                while (mbTracks.length < modelTracks.length) {
                    mbTracks.push(_.clone(modelTracks[mbTracks.length]));
                }

                while (mbTracks.length > modelTracks.length) {
                    mbTracks.pop();
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

                    // Show alert
                    currentAlert.set({
                        header: 'Error saving changes:',
                        message: xhr.statusText + ' (' + xhr.status + ')',
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
    // Alert view
    //

    var AlertView = Backbone.View.extend({
        el: $('#alert-area'),

        events: {
            'closed.bs.alert': 'onClosed',
        },

        template: _.template($('#alert-template').html()),

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);
        },

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            return this;
        },

        onClosed: function() {
            this.model.set({ header: null, message: null });
        },
    });

    var alertView = new AlertView({ model: currentAlert });


    //
    // Player views
    //

    var PlayerView = Backbone.View.extend({
        tagName: 'div',

        events: {
            'click .panel-heading': 'onToggleView',
        },

        initialize: function() {
            var self = this;

            this.expanded = false;
            this.iframe = null;
            this.activeRadio = null;
            this.headingState = null;

            $(window).on('message', function(event) {
                var ev = event.originalEvent;
                var data;

                if (self.iframe && ev.source === self.iframe.contentWindow) {
                    data = JSON.parse(ev.data);
                    if (data && data.codplayer
                        && data.codplayer.state
                        && data.codplayer.state.summary
                        && self.headingState) {
                        self.headingState.text(data.codplayer.state.summary);
                    }
                    else {
                        console.warning('unexpected message: %j', data);
                    }
                }
            });

            this.listenTo(Backbone, 'play-disc', this.onPlayDisc);
        },

        template: _.template($('#player-template').html()),

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            this.iframe = this.$('iframe.player').get(0);
            this.activeRadio = this.$('input.active-player');
            this.headingState = this.$('.player-state');

            if (this.model.get('default')) {
                this.activeRadio.prop('checked', true);
            }

            return this;
        },

        onToggleView: function(event) {
            if (event.target.tagName.toUpperCase() === 'INPUT') {
                /* Ignore clicks on the radio button */
                return;
            }

            if (this.expanded) {
                this.headingState.fadeIn();
                this.$('.panel-collapse').collapse('hide');
            }
            else
            {
                // fadeOut doesn't look good together with the expanding panel
                this.headingState.hide();
                this.$('.panel-collapse').collapse('show');
            }

            this.expanded = !this.expanded;
        },

        onPlayDisc: function(discID) {
            if (this.activeRadio && this.activeRadio.prop('checked')) {
                // This is the target, so send a message to the
                // control widget in the iframe
                if (this.iframe && this.iframe.contentWindow) {
                    console.log('Telling %s to play %s', this.iframe.src, discID);
                    this.iframe.contentWindow.postMessage(
                        JSON.stringify({
                            codplayer: {
                                play: {
                                    disc: discID,
                                },
                            }
                        }), "*");
                }
                else {
                    console.warning('should send play message, but there is no iframe or window in it');
                }
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

    var discs = new DiscList();
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
            playersView = new PlayersView({ collection: collection });
            playersView.render();
        }
    });
});
