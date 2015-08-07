/**
 * Web Routes for Records
 */
module.exports = function(app, data, functions) {
  app.get('/records.html',functions.isLoggedIn(data.loggedIn), function(req, res) {
				res.render("records", {records:data.records, archive:false});
	});
  app.get('/archive.html',functions.isLoggedIn(data.loggedIn), function(req, res) {
				res.render("records", {records:data.archive, archive:true});
	});
};
