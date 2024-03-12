var CronJob = require('cron').CronJob
var conf = require('../config.json')
const ipc = require('node-ipc').default
var fs = require('fs')
var moment = require('moment-timezone')
var RECORD = require('../data/records')
ipc.config.id = 'awasarchiver'
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
      /* ipc.of.awasmain.on(
          'message',  //any event or message type your server listens for
          function(data){
              ipc.log('got a message from awas-main : '.debug, data)
          }
      ) */
  }
)

var job = new CronJob('30 * * * * *', function () { // eslint-disable-line no-unused-vars
  console.log('Archive TICK')
  var reload = false
  var records = RECORD.load(conf.database)
  if (records.length !== 0) {
    for (var r = 0; r < records.length; r++) {
      if (isOld(records[r])) {
        console.log('Archiving ' + records[r].id)
        fs.renameSync(conf.database + '/records/' + records[r].id + '.json', conf.database + '/archive/' + records[r].id + '.json')
        reload = true
      }
    }
    if (reload) {
      ipc.of.awasmain.emit('reload', 'all')
    }
  }
}, null, true, 'Europe/Berlin')

console.log("Cronjob 'Archiving' running")

function isOld (record) {
  var now = moment()
  var rs = moment(record.stop)

  if (rs.isBefore(now, 'minute')) {
    return true
  } else {
    return false
  }
}
