/**
 * Routes for Archiving
 */
module.exports = function(app, data, records, archive) {
	var CronJob = require('cron').CronJob;


	new CronJob('30 * * * * *', function() {
		startArchive(app, data, records, archive);
	}, null, true, 'Europe/Berlin');

	console.log("Cronjob 'Archiving' running");
};

function startArchive(app, data, records, archive) {
	var fs = require('fs');
	var reload = false;
	if (data.records.length !== 0) {
		for (var r = 0; r < data.records.length; r++) {
			if (isOld(data.records[r])) {
				console.log("Archiving " + data.records[r].id);
				fs.renameSync(app.database + "/records/" + data.records[r].id + ".json", app.database + "/archive/" + data.records[r].id + ".json");
				reload = true;
			}
		}
		if (reload) {
			data.records = records.load(app.database);
			data.archive = archive.load(app.database);
		}
	}
}

function isOld(record) {
	var moment = require('moment-timezone');
	var now = moment().tz("Europe/Berlin");
	var rs = moment(record.stop).tz("Europe/Berlin");

	if (rs.isBefore(now, "minute")) {
		return true;
	} else {
		return false;
	}
}
