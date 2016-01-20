/**
 * Module dependencies.
 */

require("nice-console")(console);

var express = require('express'),
	app = express(),
	fs = require('fs'),
	https = require('https'),
	http = require('http'),
	path = require('path'),
	pack = require('./package.json'),
	cluster = require("cluster"),
	conf = require('./config.json'),
	functions = require('./functions.js'),
	stylus = require('stylus'),
	nib = require('nib'),
	records = require('./data/records'),
	users = require('./data/users'),
	archive = require('./data/archive'),
	crons = require('./data/crons'),
	bodyParser = require("body-parser");
if (cluster.isMaster) {
if (typeof process.argv[2] !== 'undefined') {
	port = process.argv[2];
} else {
	port = conf.web_port;
}
var secure_port = conf.secure_port;


app.title = pack.name;
app.author = pack.author;
app.version = pack.version;
app.database = conf.database;
app.downloads = conf.downloads;
app.ftp_port = conf.ftp_port;
var hskey = fs.readFileSync(__dirname + '/awas-key.pem');
var hscert = fs.readFileSync(__dirname + '/awas-cert.pem');
var https_options = {
	key: hskey,
	cert: hscert
};

function compile(str, path) {return stylus(str).set('filename', path).use(nib()).import('nib');}


app.set('views', __dirname + '/views');
app.set('view engine', 'jade');
app.use(stylus.middleware({
	src: __dirname + '/style',
	dest: __dirname + '/public/css',
	compile: compile,
	force: true,
	debug: true
})); //stylus
app.use(bodyParser.json());
app.use(express.static(__dirname + '/public'));

var data = {}; //All Data. Will be updated by data routes
data.records = records.load(app.database);
data.archive = archive.load(app.database);
data.crons = crons.load(app.database);
data.users = users.load(app.database);
data.loggedIn = [];
data.admins = [];
console.log(data.admins);

// Routes
//Contoller
require('./controls/streamrip')(app, data, records);
require('./controls/archiver')(app, data, records, archive);
require('./controls/ftpserver')(app, data);
require('./controls/dlcleaner')(app);
//Web
require('./website/root')(app, data, functions);
require('./website/records')(app, data, functions, records, archive);

require('./website/login')(app, data, functions, users);
require('./website/user')(app, data, functions, users);
require('./website/files')(app, data, functions);

https.createServer(https_options,app).listen(secure_port);
console.log(app.title + " " + app.version + " running secure on Port " + secure_port);

var insecureServer = http.createServer(app);
insecureServer.on('request', function(req, res) {
	res.statusCode = 302;
	res.setHeader(
		'Location', 'https://' + req.headers.host.replace(/:\d+/, ':' + secure_port) + req.url
	);
	res.end();
});
insecureServer.listen(port);
console.log("Redirecting http on " + port + " to " + secure_port);

Object.keys(cluster.workers).forEach(function(id) {
	cluster.workers[id].on('message', function(msg) {
		if (!msg.type.startsWith("axm")) {
			data.crons = [];
			data.crons = crons.load(app.database);
		}
	});
});

var croncontrol = {
workers: [],
load: function(app, data, crons) {
	Object.keys(cluster.workers).forEach(function(id) {
		console.log("Killing "+id);
		cluster.workers[id].send('STOP');
	});

	for (var x = 0; x < data.crons.length; x++) {
		var cron = data.crons[x];
		try {
				console.log("Starting Worker " + cron.id);
				var new_worker_env = {};
				new_worker_env.WORKER_ID = cron.id;
				new_worker_env.WORKER_DOWNLOADS = app.downloads;
				new_worker_env.WORKER_DATABASE = app.database;
				var new_worker = cluster.fork(new_worker_env);
				this.workers.push(new_worker);
			} catch (e) {
				console.error(e.toString());
			}
	}
}
};


croncontrol.load(app,data,crons);
require('./website/crons')(app, data, functions, crons, croncontrol);
} else {
	require("./customcrons.js");
}
