/**
 * Main Routes
 */
module.exports = function(app, data) {
	app.get('/favicon.ico', function(req, res) {
		res.sendfile(__dirname + '/public/img/favicon.ico');
	});

	app.get('/', function(req, res) {
		res.render("records", data);
	});
};
