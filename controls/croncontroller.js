var path = require('path')
var conf = require('../config.json')
var CRONS = require('../data/crons')
const ipc = require('node-ipc')
const fork = require('child_process').fork
const childprogram = path.resolve('cron.js')
const options = {
  stdio: [ 'pipe', 'pipe', 'pipe', 'ipc' ]
}
var crons = CRONS.load(conf.database)
var childs = {}
ipc.config.id = 'awascroncontrol'
ipc.config.retry = 1500
ipc.config.silent = true

ipc.connectTo(
  'awasmain',
  function () {
    ipc.of.awasmain.on(
          'connect',
          function () {
            ipc.log('## connected to awasmain ##'.rainbow, ipc.config.delay)
          }
      )
    ipc.of.awasmain.on(
          'disconnect',
          function () {
            ipc.log('disconnected from awasmain'.notice)
          }
      )
    ipc.of.awasmain.on(
        'cronstart',
        function (id) {
          childs[id] = fork(childprogram, [id], options)
        }
    )
    ipc.of.awasmain.on(
        'cronrefresh',
        function (id) {
          childs[id].send('stop')
          childs[id] = fork(childprogram, [id], options)
        }
    )
    ipc.of.awasmain.on(
      'cronremove',
      function (id) {
        childs[id].send('stop')
        delete childs[id]
      }
  )
  }
)

for (var x = 0; x < crons.length; x++) {
  var cron = crons[x]
  try {
    console.log('Starting Worker ' + cron.id)
    childs[cron.id] = fork(childprogram, [cron.id], options)
  } catch (e) {
    console.error('[ERR]: ' + e.toString())
  }
}

console.log("'CronControl' running")
