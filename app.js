/**
 * Module dependencies.
 */

require("nice-console")(console);

var express = require('express'),
	app = express(),
	fs = require('fs'),
	server = require('http').createServer(app),
	path = require('path'),
	pack = require('./package.json'),
	conf = require('./config.json'),
	functions = require('./functions.js'),
	stylus = require('stylus'),
	nib = require('nib'),
	records = require('./data/records')(app, data), //TODO CRUD on records, R on archive, chokidar, initial readin
	users = require('./data/users'), //TODO: CRUD on users, token-mgmt, login
	bodyParser = require("body-parser");

if (typeof process.argv[2] !== 'undefined') {
	port = process.argv[2];
} else {
	port = conf.web_port;
}

app.title = pack.name;
app.author = pack.author;
app.version = pack.version;
app.database = conf.database;
app.downloads = conf.downloads;
app.ftp_port = conf.ftp_port;

function compile(str, path) {
	return stylus(str)
		.set('filename', path)
		.use(nib())
		.import('nib');
}


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
data.records = [];
data.archive = [];

data.users = users.load(app.database);

data.loggedIn = []; //TODO:remove, debug
data.loggedIn.push("1"); //TODO:remove, debug

// Routes
//Contoller
require('./controls/streamrip')(app, data); //TODO: control the streamrippers via cron
require('./controls/ftpserver')(app, data);

//Web
require('./website/root')(app, data, functions);
require('./website/records')(app, data, functions); //TODO All Routes with Records and Archive
require('./website/login')(app, data, functions); //TODO The One Login route + POST to login
require('./website/user')(app, data, functions, users);
require('./website/files')(app, data, functions);

server.listen(port);
console.log(app.title + " " + app.version + " running on Port " + port);
