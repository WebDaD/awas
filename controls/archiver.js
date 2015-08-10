/**
 * Routes for Archiving
 */
module.exports =  function(app, data, records, archive) {
	var CronJob = require('cron').CronJob;
	var archivejob = new CronJob('0 * * * * *', startArchive(app,data,records,archive));
	console.log("Cronjob 'Archiving' running");
	archivejob.start();
};
function startArchive(app, data, records, archive) {
	var fs = require('fs');
	var reload = false;
	if (data.records.length === 0) {
		console.log("No records ... ");
	} else {
		console.log("Starting Archiving ... ");
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
	var d = new Date();
	var t = record.stop.split(/[\s.:]+/); //10.08.2015 16:52
	var rs = new Date(t[2]+"-"+t[1]+"-"+t[0]+"T"+t[3]+":"+t[4]+":00");
	if (rs.getTime() < d.getTime()) {
		return true;
	} else {
		return false;
	}
}
