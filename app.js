/**
 * Module dependencies.
 */
var express = require('express')
var app = express()
var http = require('http')
var path = require('path')
var pack = require('./package.json')
var conf = require('./config.json')
var functions = require('./functions.js')
var stylus = require('stylus')
var nib = require('nib')
var records = require('./data/records')
var users = require('./data/users')
var archive = require('./data/archive')
var crons = require('./data/crons')
var bodyParser = require('body-parser')
var port

app.title = pack.name
app.author = pack.author
app.version = pack.version
app.database = conf.database
app.downloads = conf.downloads

app.set('views', path.join(__dirname, 'views'))
app.set('view engine', 'jade')
app.use(stylus.middleware({
  src: path.join(__dirname, 'style'),
  dest: path.join(__dirname, 'public/css'),
  compile: compile,
  force: true,
  debug: true
})) // stylus
app.use(bodyParser.json())
app.use(express.static(path.join(__dirname, 'public')))

var data = {} // All Data. Will be updated by data routes
data.records = records.load(app.database)
data.archive = archive.load(app.database)
data.crons = crons.load(app.database)
data.users = users.load(app.database)
data.loggedIn = []
data.admins = []

const ipc = require('node-ipc')
ipc.config.id = 'awasmain'
ipc.config.retry = 1500
ipc.config.silent = true
ipc.serve(function () {
  ipc.server.on('reload', function (message) {
    data.records = records.load(app.database)
    data.archive = archive.load(app.database)
    console.log(message)
  })
  ipc.server.on(
    'socket.disconnected',
    function (socket, destroyedSocketID) {
      ipc.log('client ' + destroyedSocketID + ' has disconnected!')
    }
)
})
ipc.server.start()

function compile (str, path) { return stylus(str).set('filename', path).use(nib()).import('nib') }

if (typeof process.argv[2] !== 'undefined') {
  port = process.argv[2]
} else {
  port = conf.web_port
}

// Routes
require('./website/root')(app, data, functions)
require('./website/records')(app, data, functions, records, archive)
require('./website/crons')(app, data, functions, crons, ipc)
require('./website/login')(app, data, functions, users)
require('./website/user')(app, data, functions, users)
require('./website/files')(app, data, functions)

http.createServer(app).listen(port)
console.log(app.title + ' ' + app.version + ' running on Port ' + port)
