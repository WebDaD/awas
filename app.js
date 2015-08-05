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
	stylus = require('stylus'),
	nib = require('nib'),
	port = 80;

if (typeof process.argv[2] !== 'undefined') {
	port = process.argv[2];
}

app.title = pack.name;
app.author = pack.author;
app.version = pack.version;

function compile(str, path) {
	  return stylus(str)
	    .set('filename', path)
	    .use(nib())
	    .import('nib')
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

// Routes
// Data
require('./data/records')(app, data); //TODO CRUD on records, R on archive, chokidar, initial readin
require('./data/users')(app, data); //TODO: CRUD on users, token-mgmt, login

//Contoller
require('./controls/streamrip')(app, data); //TODO: control the streamrippers

//Web
require('./website/root')(app, data);
require('./website/records')(app, data); //TODO All Routes with Records and Archive
require('./website/login')(app, data); //TODO The One Login route
require('./website/user')(app, data); //TODO All Routes with User data

server.listen(port);
console.log(app.title + " " + app.version + " running on Port " + port);
