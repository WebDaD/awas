var conf = require('../config.json')
var RECORDS = require('../data/records')
var moment = require('moment')
var CronJob = require('cron').CronJob
const childProcess = require('child_process')
var records = RECORDS.load(conf.database)

var job = new CronJob('00 * * * * *', function () { // eslint-disable-line no-unused-vars
  console.log('RC TICK')
  records = RECORDS.load(conf.database)
  if (records.length !== 0) {
    for (var r = 0; r < records.length; r++) {
      var rec = records[r]
      var now = moment().tz('Europe/Berlin')
      var ra = moment(rec.start).tz('Europe/Berlin')
      var rs = moment(rec.stop).tz('Europe/Berlin')
      var length = moment.duration(rs.diff(ra)).asSeconds()
      if (now.isBetween(ra, rs)) {
        var commando = ''
        var timeout = length
        if (rec.command === 'mplayer') {
          commando = 'mplayer -dumpstream -dumpfile ' + conf.downloads + '/' + rec.filename + '_id-' + rec.id + '.' + rec.type + ' ' + rec.url
        } else if (rec.command === 'vlc') {
          commando = 'vlc ' + rec.url + ' --sout file/' + rec.type + ':' + conf.downloads + '/' + rec.filename + '_id-' + rec.id + '.' + rec.type
        } else { // streamripper
          commando = 'streamripper ' + rec.url + ' -a ' + conf.downloads + '/' + rec.filename + '_id-' + rec.id + ' -A --quiet -l ' + length + ' -u winamp'
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
  }
}, null, true, 'Europe/Berlin')

console.log("'RecordControl' running")
