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

	app.get('/', functions.isLoggedIn(data.loggedIn), function(req, res) {
		res.render("records", {
			records: data.records,
			archive: false
		});
	});

	app.get('/space.:command(html|free|used|total|downloads|database|pfree)', functions.isLoggedIn(data.loggedIn), function(req, res) {
		var diskspace = require('diskspace');
		var getSize = require('get-folder-size');
		var filesize = require('filesize');
		switch (req.params.command) {
			case "free":
				diskspace.check('/', function(err, total, free, status) {
					return res.send(filesize(free).toString());
				});
				break;
			case "pfree":
			diskspace.check('/', function(err, total, free, status) {
				var percent_free = Math.round((100*(free))/total);
				return res.send(percent_free.toString()+"%");
			});
			break;
			case "used":
				diskspace.check('/', function(err, total, free, status) {
					var used = total - free;
					return res.send(filesize(used).toString());
				});
				break;
			case "total":
				diskspace.check('/', function(err, total, free, status) {
					return res.send(filesize(total).toString());
				});
				break;
			case "downloads":
				getSize(app.downloads, function(err, size) {
					return res.send(filesize(size).toString());
				});
				break;
			case "database":
				getSize(app.database, function(err, size) {
					return res.send(filesize(size).toString());
				});
				break;
			case "html":
				diskspace.check('/', function(err, total, free, status) {
					getSize(app.downloads, function(err, downloads) {
						getSize(app.database, function(err, database) {
							var percent_used = Math.round((100*(total - free))/total);
							var percent_free = 100 - percent_used;
							return res.render("space", {
								free: filesize(free),
								total: filesize(total),
								used: filesize((total - free)),
								downloads: filesize(downloads),
								database: filesize(database),
								percent_used:percent_used,
								percent_free:percent_free
							});
						});
					});
				});
				break;
			default:
				return res.send(req.params.command + " not recognized.");
		}
	});
};
