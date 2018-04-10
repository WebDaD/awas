/**
 * Module dependencies.
 */
var express = require('express')
var app = express()
var http = require('http')
var path = require('path')
var pack = require('./package.json')
var cluster = require('cluster')
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

function compile (str, path) { return stylus(str).set('filename', path).use(nib()).import('nib') }

if (cluster.isMaster) {
  if (typeof process.argv[2] !== 'undefined') {
    port = process.argv[2]
  } else {
    port = conf.web_port
  }

  app.title = pack.name
  app.author = pack.author
  app.version = pack.version
  app.database = conf.database
  app.downloads = conf.downloads
  app.ftp_port = conf.ftp_port

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
  console.log(data.admins)

// Routes
// Contoller
  require('./controls/streamrip')(app, data, records)
  require('./controls/archiver')(app, data, records, archive)
  require('./controls/ftpserver')(app, data)
  require('./controls/dlcleaner')(app)
// Web
  require('./website/root')(app, data, functions)
  require('./website/records')(app, data, functions, records, archive)

  require('./website/login')(app, data, functions, users)
  require('./website/user')(app, data, functions, users)
  require('./website/files')(app, data, functions)

  http.createServer(app).listen(port)
  console.log(app.title + ' ' + app.version + ' running on Port ' + port)

  Object.keys(cluster.workers).forEach(function (id) {
    cluster.workers[id].on('message', function (msg) {
      if (!msg.type.startsWith('axm')) {
        data.crons = []
        data.crons = crons.load(app.database)
      }
    })
  })

  var croncontrol = {
    workers: [],
    load: function (app, data, crons) {
      Object.keys(cluster.workers).forEach(function (id) {
        console.log('Killing ' + id)
        cluster.workers[id].send('STOP')
      })

      for (var x = 0; x < data.crons.length; x++) {
        var cron = data.crons[x]
        try {
          console.log('Starting Worker ' + cron.id)
          var newWorkerEnv = {}
          newWorkerEnv.WORKER_ID = cron.id
          newWorkerEnv.WORKER_DOWNLOADS = app.downloads
          newWorkerEnv.WORKER_DATABASE = app.database
          var newWorker = cluster.fork(newWorkerEnv)
          this.workers.push(newWorker)
        } catch (e) {
          console.error(e.toString())
        }
      }
    }
  }

  croncontrol.load(app, data, crons)
  require('./website/crons')(app, data, functions, crons, croncontrol)
} else {
  require('./customcrons.js')
}
