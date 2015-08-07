/**
 * Web Routes for Records
 */
module.exports = function(app, data, functions) {

	app.get('/files.html',functions.isLoggedIn(data.loggedIn), function(req, res) {
			readInFiles(app.downloads, function(err, files) {
				if (err) {
					data.files = [err];
				} else {
					data.files = [];
					var fs = require('fs');
						var filesize = require('filesize');
					for(var x=0;x < files.length;x++){
						var f = {};
						var fst = fs.statSync(app.downloads +'/'+files[x]);
						f.name = files[x];
						f.size = filesize(fst.size);
						f.created = fst.ctime;
						data.files.push(f);
					}
				}
				data.admin = true;//TODO: remove, debug
				res.render("files", data);
			});
	});
	app.get('/files/:file',functions.isLoggedIn(data.loggedIn), function(req, res) {
		if (typeof req.params.file === 'undefined') {
			res.send('Error');
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
};

function readInFiles(path, callback) {
	var fs = require('fs');
	fs.readdir(path, function(err, files) {
		callback(err, files);
	});
}
