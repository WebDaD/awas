/**
 * Routes for Streamripper
 */
module.exports = function(app, data, records) {
	var CronJob2 = require('cron').CronJob;


	new CronJob2('00 * * * * *', function() {
		startRip(app, data, records);
	}, null, true, 'Europe/Berlin');

	console.log("Cronjob 'StreamRipper' running");
};

function startRip(app, data, records) {
	var fs = require('fs');
	var reload = false;
	if (data.records.length !== 0) {
		for (var r = 0; r < data.records.length; r++) {
			if (isOnTime(data.records[r])) {
				startRipper(app.downloads, data.records[r], function(record,pid) {
					record.streamripper_pid = pid;
					records.updateRecord(app.database, record, function() {
						data.records = records.load(app.database);
					});
				});
			}
		}
	}
}

function startRipper(downloads, record, callback) { //callback(record,pid)
  var moment = require('moment-timezone');
  var child_process = require('child_process');
  var start = moment(record.start).tz("Europe/Berlin");
  var stop = moment(record.stop).tz("Europe/Berlin");

	var Seconds_Between_Dates = stop.diff(start,"seconds");

	var commando = "streamripper " + record.url + " -a " + downloads + "/" + record.filename+"_id-"+record.id + " -A --quiet -l " + Seconds_Between_Dates;
	console.log("Executing: '" + commando + "'");
	var child = child_process.exec(commando, function() {
		callback(record,child.pid);
	});
}

function isOnTime(record) {
  var moment = require('moment-timezone');
	var now = moment().tz("Europe/Berlin");
	var rs = moment(record.start).tz("Europe/Berlin");
	if (now.isSame(rs,"minute")) {
		return true;
	} else {
		return false;
	}
}
