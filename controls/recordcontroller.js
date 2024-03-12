var conf = require('../config.json')
var RECORDS = require('../data/records')
var moment = require('moment')
var CronJob = require('cron').CronJob
const childProcess = require('child_process')
var records = RECORDS.load(conf.database)

var job = new CronJob('* * * * *', function () { // eslint-disable-line no-unused-vars
  console.log('RC TICK')
  records = RECORDS.load(conf.database)
  if (records.length !== 0) {
    for (var r = 0; r < records.length; r++) {
      var rec = records[r]
      if (rec.recording) {
        recording = true
      } else {
        recording = false
      }
      var now = moment()
      var ra = moment(rec.start)
      var rs = moment(rec.stop)
      var length = moment.duration(rs.diff(ra)).asSeconds()
      if (!recording && now.isBetween(ra, rs)) {
        var commando = ''
        var timeout = length
        if (rec.command === 'mplayer') {
          commando = 'mplayer -dumpstream -dumpfile ' + conf.downloads + '/' + rec.filename.trim() + '_id-' + rec.id + '.' + rec.type + ' ' + rec.url.trim()
        } else if (rec.command === 'vlc') {
          commando = 'vlc ' + rec.url.trim() + ' --sout file/' + rec.type + ':' + conf.downloads + '/' + rec.filename.trim() + '_id-' + rec.id + '.' + rec.type
        } else { // streamripper
          commando = 'streamripper ' + rec.url.trim() + ' -a ' + conf.downloads + '/' + rec.filename.trim() + '_id-' + rec.id + ' -A --quiet -l ' + length + ' -u winamp'
          timeout = -1
        }

        console.log("RC: Executing: '" + commando + "'")
        var options = {}
        if (timeout > 0) {
          options.timout = timeout
        }
        childProcess.exec(commando, options, function () {
          var m = {}
          m.type = 'custom'
          m.text = 'reload'
          m.sender = rec.id
        })
        setTimeout(function() {
          childProcess.exec("pgrep -f \"" + commando + "\"", options, function (error, stdout) {
            rec.streamripper_pid = stdout
            rec.recording = true
            RECORDS.updateRecord(conf.database, rec, function(error, record) {
              if (error) {
                console.error(error)
              } else {
                console.log("RC: Record " + record.id + " updated with pid " + record.streamripper_pid)
              }
            })
          })
        }, 2000);
      } else {
        console.log("RC Record " + rec.id + " is already recording")
      }
    }
  }
}, null, true, 'Europe/Berlin')

console.log("'RecordControl' running: " + job.running)
