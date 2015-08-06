/**
 * Web Routes for Records
 */
module.exports = function(app, data, functions) {

	app.get('/files.html', function(req, res) {
		if (functions.isLoggedIn(req, data.loggedIn)) {
			readInFiles(app.downloads, function(err, files) {
				if (err) {
					data.files = [err];
				} else {
					data.files = files;
				}
				res.render("files", data);
			});
		} else {
			res.render("login", data);
		}
	});
	app.get('/files/:file', function(req, res) {
		if (typeof req.params.file === 'undefined') {
			res.send('Error');
		} else {
			if (functions.isLoggedIn(req, data.loggedIn)) {
				var path = require('path');
				var mime = require('mime');
				var fs = require('fs');

				var file = app.downloads +'/'+ req.params.file;

				var filename = path.basename(file);
				var mimetype = mime.lookup(file);

				res.setHeader('Content-disposition', 'attachment; filename=' + filename);
				res.setHeader('Content-type', mimetype);

				var filestream = fs.createReadStream(file);
				filestream.pipe(res);

			} else {
				res.render("login", data);
			}
		}
	});
};

function readInFiles(path, callback) {
	var fs = require('fs');
	fs.readdir(path, function(err, files) {
		callback(err, files);
	});
}
