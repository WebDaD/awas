require("nice-console")(console);

var express = require('express'),
	app = express(),
	fs = require('fs'),
	path = require('path'),
	tcj = require('cron').CronJob,
	child_process = require('child_process'),
	jsonfile = require('jsonfile')
	;

var cronid = process.env.WORKER_ID;
var cron = jsonfile.readFileSync(process.env.WORKER_DATABASE+"/crons/"+cronid+".json");
var downloads = process.env.WORKER_DOWNLOADS;
console.log("Adding Cron " + cronid + " with tab " + cron.tab);

new tcj('00 ' + cron.tab, function() {

	var commando = "streamripper " + cron.url + " -a " + downloads + "/" + cron.times_run + "-" + cron.filename + "_id-" + cronid + " -A --quiet -l " + cron.length;
	console.log("Executing: '" + commando + "'");

	var child = child_process.exec(commando, function() {
		cron.times_run++;
		var m = {};
		m.type = "custom";
		m.text = "reload";
		m.sender = cronid;
		process.send(m);
	});


}, null, true, 'Europe/Berlin');
process.on('message',function(msg) {
	if(msg.trim() == "STOP"){
	console.log("Asked to quit: "+cronid);
					process.exit();
				}
				});
