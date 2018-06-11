var conf = require('../config.json')
var CRONS = require('../data/crons')
var CronJob = require('cron').CronJob
const fork = require('child_process').fork
const childprogram = '/opt/awas/controls/cron.js'
const options = {
  stdio: [ 'pipe', 'pipe', 'pipe', 'ipc' ]
}
var crons = CRONS.load(conf.database)
var childs = {}

for (var x = 0; x < crons.length; x++) {
  var cron = crons[x]
  try {
    console.log('Starting Worker ' + cron.id)
    childs[cron.id] = fork(childprogram, [cron.id], options)
    console.log('Worker' + cron.id + ' living: ' + childs[cron.id].connected)
    childs[cron.id].on('message', function (m) { console.log(m) })
  } catch (e) {
    console.error('[ERR]: ' + e.toString())
  }
}

var job = new CronJob('* * * * *', function () {
  var oldCrons = crons
  crons = CRONS.load(conf.database)
  console.log('CC TICK (' + crons.length + ' Crons)')
  for (var c = 0; c < crons.length; c++) {
    var cron = crons[c]
    for (var oc = 0; oc < oldCrons.length; oc++) {
      if (oldCrons[oc].id === cron.id && !CRONS.equalCrons(cron, oldCrons[oc])) {
        console.log('Re-Starting Worker ' + cron.id)
        childs[cron.id].send('stop')
        childs[cron.id] = fork(childprogram, [cron.id], options)
        childs[cron.id].on('message', function (m) { console.log(m) })
      }
    }
    if (typeof childs[cron.id] === 'undefined') {
      console.log('Starting Worker ' + cron.id)
      childs[cron.id] = fork(childprogram, [cron.id], options)
      childs[cron.id].on('message', function (m) { console.log(m) })
    }
  }
  for (var childID in childs) {
    if (childs.hasOwnProperty(childID)) {
      if (!CRONS.exists(crons, childID)) {
        console.log('Stopping Worker ' + childID)
        childs[childID].send('stop')
        delete childs[childID]
      }
    }
  }
}, null, true, 'Europe/Berlin')

console.log("'CronControl' running: " + job.running)
