var conf = require('../config.json')
var RECORDS = require('../data/records')
var CronJob = require('cron').CronJob
const ipc = require('node-ipc')
const childProcess = require('child_process')
var records = RECORDS.load(conf.database)
ipc.config.id = 'awasrecordcontrol'
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
        'recordstart',
        function (id) {
          records = RECORDS.load(conf.database)
        }
    )
    ipc.of.awasmain.on(
      'recordstop',
      function (id) {
        // TODO: Stop a record
      }
  )
    ipc.of.awasmain.on(
        'recordrefresh',
        function (id) {
          records = RECORDS.load(conf.database)
        }
    )
    ipc.of.awasmain.on(
      'recordremove',
      function (id) {
        records = RECORDS.load(conf.database)
      }
  )
  }
)

var job = new CronJob('00 * * * * *', function () { // eslint-disable-line no-unused-vars
  console.log('RC TICK')
  if (records.length !== 0) {
    for (var r = 0; r < records.length; r++) {
      var rec = records[r]
      var commando = ''
      var timeout = rec.length
      if (rec.command === 'mplayer') {
        commando = 'mplayer -dumpstream -dumpfile ' + conf.downloads + '/' + rec.filename + '_id-' + rec.id + '.' + rec.type + ' ' + rec.url
      } else if (rec.command === 'vlc') {
        commando = 'vlc ' + rec.url + ' --sout file/' + rec.type + ':' + conf.downloads + '/' + rec.filename + '_id-' + rec.id + '.' + rec.type
      } else { // streamripper
        commando = 'streamripper ' + rec.url + ' -a ' + conf.downloads + '/' + rec.filename + '_id-' + rec.id + ' -A --quiet -l ' + rec.length + ' -u winamp'
        timeout = -1
      }

      console.log("CRON: Executing: '" + commando + "'")

      childProcess.exec(commando, {timeout: timeout}, function () {
        var m = {}
        m.type = 'custom'
        m.text = 'reload'
        m.sender = rec.id
      })
    }
  }
  // TODO: check if there are records to start
}, null, true, 'Europe/Berlin')

console.log("'RecordControl' running")
