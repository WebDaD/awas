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
	port = 80;

if (typeof process.argv[2] !== 'undefined') {
	port = process.argv[2];
}

app.title = pack.name;
app.author = pack.author;
app.version = pack.version;
app.database = conf.database;
app.downloads = conf.downloads;

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
app.use(express.static(__dirname + '/public'));

var data = {}; //All Data. Will be updated by data routes

data.loggedIn = []; //TODO:remove, debug
data.loggedIn.push("1");//TODO:remove, debug

// Routes
// Data
require('./data/records')(app, data); //TODO CRUD on records, R on archive, chokidar, initial readin
require('./data/users')(app, data); //TODO: CRUD on users, token-mgmt, login

//Contoller
require('./controls/streamrip')(app, data); //TODO: control the streamrippers

//Web
require('./website/root')(app, data, functions);
require('./website/records')(app, data, functions); //TODO All Routes with Records and Archive
require('./website/login')(app, data, functions); //TODO The One Login route
require('./website/user')(app, data, functions); //TODO All Routes with User data
require('./website/files')(app, data, functions); //TODO All Routes to show and download files

server.listen(port);
console.log(app.title + " " + app.version + " running on Port " + port);
