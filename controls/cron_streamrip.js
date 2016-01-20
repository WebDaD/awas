/**
 * Routes for Streamripper
 */
module.exports = {
	load: function(app, data, crons) {
		for (var x = 0; x < data.crons.length; x++) {
			var tcj = require('cron').CronJob;
			var c = data.crons[x];
			new tcj('00 ' + c.tab, function() {
				startRip(app, c, crons, data);
			}, null, true, 'Europe/Berlin');
		}
		console.log("Custom CronJobs running");
	}
};

function startRip(app, cron, crons, data) {
	var fs = require('fs');
	var child_process = require('child_process');

	var commando = "streamripper " + cron.url + " -a " + app.downloads + "/" + cron.times_run + "-" + cron.filename + "_id-" + cron.id + " -A --quiet -l " + cron.length+ " -u winamp";
	console.log("Executing: '" + commando + "'");

	var child = child_process.exec(commando, function() {
		cron.times_run++;
		crons.updateCron(app.database, cron, function() {
			data.crons = crons.load(app.database);
		});
	});
}
