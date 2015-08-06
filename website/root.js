/**
 * Main Routes
 */
module.exports = function(app, data, functions) {
	app.get('/favicon.ico', function(req, res) {
		res.sendFile(__dirname + '/public/img/favicon.ico');
	});

	app.get('/', function(req, res) {
		var user = functions.getUserFromRequest(req);
		if(functions.containsObject(user,data.loggedIn)){
				res.render("records", data);
		} else {
				//res.render("login", data);
				res.render("records", data); //TODO: debug, switch
		}
	});
};
