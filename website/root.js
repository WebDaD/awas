/**
 * Main Routes
 */
module.exports = function(app, data, functions) {
	app.get('/favicon.ico', function(req, res) {
		res.sendFile(__dirname + '/public/img/favicon.ico');
	});
	app.get('/manifest.json', function(req, res) {
		res.sendFile(__dirname + '/public/manifest.json');
	});

	app.get('/',functions.isLoggedIn(data.loggedIn), function(req, res) {
				res.render("records", data);
	});
};
