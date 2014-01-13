// codplayer web admin GUI
//
// Copyright 2014 Peter Liljenberg <peter.liljenberg@gmail.com>
//
// Distributed under an MIT license, please see LICENSE in the top dir.

$(function(){

    //
    // Disc model and collection
    //
    
    var Disc = Backbone.Model.extend({
        idAttribute: 'disc_id',

        initialize: function() {
        },
    });

    var DiscList = Backbone.Collection.extend({
        model: Disc,

        url: 'discs'
    });

    var discs = new DiscList();

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
    // Table view of a disc
    //

    var DiscRowView = Backbone.View.extend({
        tagName: 'li',
        className: 'list-group-item disc',

        events: {
            'click .disc-row': 'toggleDetails',
            'click .edit-disc': 'startEdit',
            'click .save-edit': 'saveEdit',
            'click .cancel-edit': 'cancelEdit',
        },

        rowTemplate: _.template($('#disc-row-template').html()),
        detailTemplate: _.template($('#disc-detail-template').html()),
        
        template: function(obj) {
            var html = this.rowTemplate(obj);
            if (this.showDetail) {
                html += this.detailTemplate(obj);
            }
            return html;
        },

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);

            this.showDetail = false;
            this.editing = false;
        },

        render: function() {
            this.setEditing(this.editing);
            this.$el.html(this.template(this.model.toJSON()));
            return this;
        },

        setEditing: function(editing) {
            this.editing = editing;
            if (editing) {
                this.$('.disc-row').removeClass('hover-row');
                this.$('.track-row').removeClass('hover-row');
                this.$('.view-only').hide();
                this.$('.edit-only').show();
            }
            else {
                this.$('.disc-row').addClass('hover-row');
                this.$('.track-row').addClass('hover-row');
                this.$('.edit-only').hide();
                this.$('.view-only').show();
            }
        },

        toggleDetails: function() {
            var that = this;

            // Can't toggle while editing
            if (this.editing) {
                return;
            }

            if (this.showDetail) {
                this.$('.disc-details').slideUp(function() {
                    that.showDetail = false;
                    that.render();
                });
            }
            else {
                if (typeof this.model.get('tracks') === 'number') {
                    // We only have the partial disc info, so fetch
                    // the full structure

                    this.model.fetch({
                        success: function() {
                            that.showDetails();
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
                    this.showDetails();
                }
                
            }
        },

        showDetails: function() {
            this.showDetail = true;
            this.render();
            this.$('.disc-details').slideDown();
        },

        startEdit: function() {
            // Ensure the forms are enabled
            this.$('fieldset').prop('disabled', false);

            this.setEditing(true);
        },

        saveEdit: function() {
            // Get the values of the edit fields.  Put them all into a
            // map so we can call model.save() and have them all
            // stashed to the server atomically(ish)

            var that = this;
            var save = {};

            var getTrackValues = function(field, func) {
                that.$('[data-edit-field="' + field + '"]').each(function(elementIndex, element) {
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

            getTrackValues('track-artist', function(track, element) {
                track.artist = element.value;
            });

            getTrackValues('track-title', function(track, element) {
                track.title = element.value;
            });

            // Do save, but don't update model until we get a response
            // from server.  Also set editing mode to false so that a
            // successful update renders the viewing mode directly.
            
            that.model.save(save, {
                wait: true,
                success: function() {
                    // Unlock fields so the Edit button is enabled again
                    that.$('fieldset').prop('disabled', false);

                    // Flip to view mode
                    that.setEditing(false);
                },

                error: function(model, xhr) {
                    // Unlock fields so the user can cancel or retry save
                    that.$('fieldset').prop('disabled', false);

                    // Show alert
                    currentAlert.set({
                        header: 'Error saving changes:',
                        message: xhr.statusText + ' (' + xhr.status + ')',
                    });
                },
            });
        },

        cancelEdit: function() {
            this.setEditing(false);
        },
    });


    //
    // List view of all discs
    //

    var DiscsView = Backbone.View.extend({
        el: $('#discs'),

        initialize: function() {
            this.listenTo(discs, 'add', this.addOne);
            this.listenTo(discs, 'reset', this.addAll);
        },

        addOne: function(disc) {
            var view = new DiscRowView({model: disc});
            this.$el.append(view.render().el);
        },

        addAll: function() {
            discs.each(this.addOne, this);
        },
    });

    var discsView = new DiscsView();


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
    // Kick everything off by fetching the list of discs
    //

    // TODO: provide progress report on this
    discs.fetch();
});