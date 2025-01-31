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
var CronJob = require('cron').CronJob

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

function compile(str, path) { return stylus(str).set('filename', path).use(nib()).import('nib') }

if (typeof process.argv[2] !== 'undefined') {
    port = process.argv[2]
} else {
    port = conf.web_port
}

// Routes
require('./website/root')(app, data, functions)
require('./website/records')(app, data, functions, records, archive)
require('./website/crons')(app, data, functions, crons)
require('./website/login')(app, data, functions, users)
require('./website/user')(app, data, functions, users)
require('./website/files')(app, data, functions)

http.createServer(app).listen(port)
console.log(app.title + ' ' + app.version + ' running on Port ' + port)

var job = new CronJob('* * * * *', function() { // eslint-disable-line no-unused-vars
    console.log('Main Database Reload')
    data.records = records.load(app.database)
    data.archive = archive.load(app.database)
    data.crons = crons.load(app.database)
    data.users = users.load(app.database)
}, null, true, 'Europe/Berlin')
setTimeout(function() { //30 seocnds to alternate
    var job2 = new CronJob('* * * * *', function() { // eslint-disable-line no-unused-vars
        console.log('Main Database Reload')
        data.records = records.load(app.database)
        data.archive = archive.load(app.database)
        data.crons = crons.load(app.database)
        data.users = users.load(app.database)
    }, null, true, 'Europe/Berlin')
}, 30000)

/**
 * Start the controls handling of the interal server 
 */
const controls_archiver = require('./controls/archiver.js')
const controls_cron = require('./controls/croncontroller.js')
const controls_dl = require('./controls/dlcleaner.js')
const controls_ftp = require('./controls/ftpserver.js')
const controls_record = require('./controls/recordcontroller.js')