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

    var DiscOverView = Backbone.View.extend({
        tagName: 'div',

        events: {
            'click .disc-row': 'onToggleDetails',
        },

        template: _.template($('#disc-row-template').html()),

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);
        },

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            return this;
        },

        onToggleDetails: function() {
            var self = this;

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


    var DiscDetailsView = Backbone.View.extend({
        tagName: 'div',
        className: 'disc-details-view',

        events: {
            'click .toggle-details': 'onToggleDetails',
            'click .edit-disc': 'onStartEdit',
            'click .fetch-musicbrainz': 'onFetchMusicbrainz',
        },

        rowTemplate: _.template($('#disc-row-template').html()),
        detailTemplate: _.template($('#disc-detail-template').html()),
        
        template: function(obj) {
            var html = this.rowTemplate(obj);
            html += this.detailTemplate(obj);
            return html;
        },

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);
        },

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            return this;
        },

        onToggleDetails: function() {
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

    var DiscEditView = Backbone.View.extend({
        tagName: 'div',

        events: {
            'click .save-edit': 'onSaveEdit',
            'click .cancel-edit': 'onCancelEdit',
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

        onCancelEdit: function() {
            this.trigger('disc-view:details');
        },
    });

    var DiscMBInfoView = Backbone.View.extend({
        tagName: 'div',

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

        onCancel: function() {
            this.trigger('disc-view:details');
        },
    });


    var MBDiscView = Backbone.View.extend({
        tagName: 'div',
        className: 'mb-disc col-xs-12 col-md-6 hover-row',
        
        events: {
            'click': 'onSelect',
        },
        
        template: _.template($('#mbdisc-template').html()),

        initialize: function() {
        },

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            return this;
        },

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
            this.headingState = null;

            $(window).on('message', function(event) {
                var ev = event.originalEvent;
                var data;

                if (self.iframe && ev.source === self.iframe.contentWindow) {
                    data = JSON.parse(ev.data);
                    self.headingState.text(data.codStateString);
                }
            });
        },

        template: _.template($('#player-template').html()),

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            this.iframe = this.$('iframe.player').get(0);
            this.headingState = this.$('.player-state');
            return this;
        },

        onToggleView: function() {
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
