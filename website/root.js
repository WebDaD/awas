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
		var dir = require('dir-util');
		var fs = require('fs');
		var filesize = require('filesize');
		switch (req.params.command) {
			case "free":
				diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
					return res.send(filesize(free2).toString());
				});
				break;
			case "pfree":
				diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
					var percent_free = Math.round((100 * (free2)) / (total2));
					return res.send(filesize(free2).toString()+" / "+percent_free.toString() + "%");
				});
				break;
			case "used":
				diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
					var used = (total2) - (free2);
					return res.send(filesize(used).toString());
				});
				break;
			case "total":
				diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
					return res.send(filesize(total2).toString());
				});
				break;
			case "downloads":
				dir.getSize(app.downloads, function(err, size) {
					return res.send(filesize(size).toString());
				});
				break;
			case "database":
				dir.getSize(app.database, function(err, size) {
					return res.send(filesize(size).toString());
				});
				break;
			case "html":
				diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
					dir.getSize(app.downloads, function(err, downloads) {
						dir.getSize(app.database, function(err, database) {
							var percent_used = Math.round((100 * ((total2) - (free2))) / (total2));
							var percent_free = 100 - percent_used;
							return res.render("space", {
								free: filesize(free2),
								total: filesize(total2),
								used: filesize(((total2) - (free2))),
								downloads: filesize(downloads),
								database: filesize(database),
								percent_used: percent_used,
								percent_free: percent_free
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
