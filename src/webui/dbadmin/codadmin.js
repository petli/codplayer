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
        tagName: 'tr',
        className: 'disc-row',

        events: {
            'click': 'toggleDetails',
        },

        template: _.template($('#disc-row-template').html()),

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);

            this.detailView = null;
        },

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            return this;
        },

        toggleDetails: function() {
            var that = this;

            if (this.detailView) {
                console.log('hiding details');
                this.detailView.remove();
                this.detailView = null;
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
            this.detailView = new DiscDetailView({ model: this.model });
            this.$el.after(this.detailView.render().el);
        },
    });


    var DiscDetailView = Backbone.View.extend({
        tagName: 'tr',
        className: 'disc-detail',

        template: _.template($('#disc-detail-template').html()),

        initialize: function() {
            this.listenTo(this.model, 'change', this.render);
        },

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
            return this;
        },
    });


    //
    // Table view of all discs
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