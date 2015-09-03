/**
 * Web Routes for Records
 */
module.exports = function(app, data, functions) {

	app.get('/files.html',functions.isLoggedIn(data.loggedIn),functions.isAdmin(data.admins), function(req, res) {
			readInFiles(app.downloads, function(err, files) {
				if (err) {
					data.files = [err];
				} else {
					data.files = [];
					var fs = require('fs');
						var filesize = require('filesize');
						var moment = require('moment');
					for(var x=0;x < files.length;x++){
						var f = {};
						var fst = fs.statSync(app.downloads +'/'+files[x]);
						f.name = files[x];
						f.size = filesize(fst.size);
						f.created = moment(fst.ctime).format("DD.MM.YYYY HH:mm:ss");
						data.files.push(f);
					}
				}
				data.admin = req.admin;
				res.render("files", data);
			});
	});
	app.get('/files/:file',functions.isLoggedIn(data.loggedIn), function(req, res) {
		if (typeof req.params.file === 'undefined') {
			res.sendStatus(404);
		} else {
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
		}
	});
	app.delete('/files/:file',functions.isLoggedIn(data.loggedIn), function(req, res) {
		if (typeof req.params.file === 'undefined') {
			res.sendStatus(400);
		} else {
				var fs = require('fs');
				var file = app.downloads+"/"+req.params.file;
				fs.unlink(file, function(err) {
					if (err) {
							res.sendStatus(500);
					} else {
						res.sendStatus(200);
					}
				});
		}
	});
};

function readInFiles(path, callback) {
	var fs = require('fs');
	fs.readdir(path, function(err, files) {
		callback(err, files);
	});
}
