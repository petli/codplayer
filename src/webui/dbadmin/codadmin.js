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
            this.$el.html(this.template(this.model.toJSON()));
            this.setEditClasses();
            return this;
        },

        setEditClasses: function() {
            if (this.editing) {
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
                console.log('hiding details');
                this.$('.disc-details').slideUp(function() {
                    that.showDetail = false;
                    that.render();
                });
            }
            else {
                if (typeof this.model.get('tracks') === 'number') {
                    // We only have the partial disc info, so fetch
                    // the full structure

                    console.log('fetching disc details');
                    
                    this.model.fetch({
                        success: function() {
                            that.showDetails();
                        },

                        error: function(model, response) {
                            alert("Couldn't fetch disc details.");
                        }
                    });
                }
                else {
                    this.showDetails();
                }
                
            }
        },

        showDetails: function() {
            console.log('showing details');
            this.showDetail = true;
            this.render();
            this.$('.disc-details').slideDown();
        },

        startEdit: function() {
            this.editing = true;
            this.setEditClasses();
        },

        saveEdit: function() {
            // TODO: get the input values
            this.editing = false;
            this.setEditClasses();
        },

        cancelEdit: function() {
            this.editing = false;
            this.setEditClasses();
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

    discsView = new DiscsView();

    //
    // Kick everything off by fetching the list of discs
    //

    // TODO: provide progress report on this
    discs.fetch();
});