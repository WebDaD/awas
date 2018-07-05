var conf = require('../config.json')
var CRONS = require('../data/crons')
var CronJob = require('cron').CronJob
var pm2 = require('pm2')
const childprogram = '/opt/awas/controls/cron.js'

var crons = CRONS.load(conf.database)
var childs = {}

pm2.connect(function (err) {
  if (err) {
    console.error(err)
    process.exit(2)
  } else {
    for (var x = 0; x < crons.length; x++) {
      var cron = crons[x]
      console.log('Starting Worker ' + cron.id)
      pm2.start({
        script: childprogram,
        name: 'CRON_' + cron.id,
        args: cron.id
      }, function (err, apps) {
        if (err) {
          console.error(err)
        } else {
          childs[cron.id] = cron
        }
      })
    }
  }
})

var job = new CronJob('* * * * *', function () {
  var oldCrons = crons
  crons = CRONS.load(conf.database)
  console.log('CC TICK (' + crons.length + ' Crons)')
  for (var c = 0; c < crons.length; c++) {
    var cron = crons[c]
    for (var oc = 0; oc < oldCrons.length; oc++) {
      if (oldCrons[oc].id === cron.id && !CRONS.equalCrons(cron, oldCrons[oc])) {
        console.log('Re-Starting Worker ' + cron.id)
        pm2.restart('CRON_' + cron.id, function (err) {
          if (err) {
            console.error(err)
          }
        })
      }
    }
    if (typeof childs[cron.id] === 'undefined') {
      console.log('Starting Worker ' + cron.id)
      pm2.start({
        script: childprogram,
        name: 'CRON_' + cron.id,
        args: cron.id
      }, function (err, apps) {
        if (err) {
          console.error(err)
        } else {
          childs[cron.id] = cron
        }
      })
    }
  }
  for (var childID in childs) {
    if (childs.hasOwnProperty(childID)) {
      if (!CRONS.exists(crons, childID)) {
        console.log('Stopping Worker ' + childID)
        pm2.delete('CRON_' + childID, function (err) {
          if (err) {
            console.error(err)
          } else {
            delete childs[childID]
          }
        })
      }
    }
  }
}, null, true, 'Europe/Berlin')

console.log("'CronControl' running: " + job.running)
