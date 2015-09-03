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
				diskspace.check('/', function(err, total, free, status) {
					diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
						return res.send(filesize(free + free2).toString());
					});
				});
				break;
			case "pfree":
			diskspace.check('/', function(err, total, free, status) {
				diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
					var percent_free = Math.round((100 * (free+free2)) / (total+total2));
					return res.send(percent_free.toString() + "%");
				});
			});
				break;
			case "used":
				diskspace.check('/', function(err, total, free, status) {
					diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
						var used = (total + total2) - (free + free2);
						return res.send(filesize(used).toString());
					});
				});
				break;
			case "total":
				diskspace.check('/', function(err, total, free, status) {
					diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
						return res.send(filesize(total + total2).toString());
					});
				});
				break;
			case "downloads":
				fs.readlink(app.downloads, function(err, target) {
					dir.getSize(target, function(err, size) {
						return res.send(filesize(size).toString());
					});
				});

				break;
			case "database":
				dir.getSize(app.database, function(err, size) {
					return res.send(filesize(size).toString());
				});
				break;
			case "html": //TODO
				diskspace.check('/', function(err, total, free, status) {
						diskspace.check('/var/mmc/', function(err, total2, free2, status2) {
					fs.readlink(app.downloads, function(err, target) {
						dir.getSize(target, function(err, downloads) {
							dir.getSize(app.database, function(err, database) {
								var percent_used = Math.round((100 * ((total+total2) - (free+free2))) / (total+total2));
								var percent_free = 100 - percent_used;
								return res.render("space", {
									free: filesize(free+free2),
									total: filesize(total+total2),
									used: filesize(((total+total2) - (free+free2))),
									downloads: filesize(downloads),
									database: filesize(database),
									percent_used: percent_used,
									percent_free: percent_free
								});
							});
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
