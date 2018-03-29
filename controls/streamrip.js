/**
 * Routes for Streamripper
 */
module.exports = function (app, data, records) {
  var CronJob2 = require('cron').CronJob

  CronJob2('00 * * * * *', function () {
    startRip(app, data, records)
  }, null, true, 'Europe/Berlin')

  console.log("Cronjob 'Recorder' running")
}

function startRip (app, data, records) {
  if (data.records.length !== 0) {
    for (var r = 0; r < data.records.length; r++) {
      if (isOnTime(data.records[r])) {
        startRipper(app.downloads, data.records[r], function (record, pid) {
          record.streamripper_pid = pid
          records.updateRecord(app.database, record, function () {
            data.records = records.load(app.database)
          })
        })
      }
    }
  }
}

function startRipper (downloads, record, callback) { // callback(record,pid)
  var moment = require('moment-timezone')
  var childProcess = require('child_process')
  var start = moment(record.start).tz('Europe/Berlin')
  var stop = moment(record.stop).tz('Europe/Berlin')

  var SecondsBetweenDates = stop.diff(start, 'seconds')

  var commando = ''
  var timeout = SecondsBetweenDates
  if (record.command === 'mplayer') {
    commando = 'mplayer -dumpstream -dumpfile ' + downloads + '/' + record.times_run + '-' + record.filename + '_id-' + record.id + '.' + record.type + ' ' + record.url
  } else if (record.command === 'vlc') {
    commando = 'vlc ' + record.url + ' --sout file/' + record.type + ':' + downloads + '/' + record.times_run + '-' + record.filename + '_id-' + record.id + '.' + record.type
  } else { // streamripper
    commando = 'streamripper ' + record.url + ' -a ' + downloads + '/' + record.times_run + '-' + record.filename + '_id-' + record.record + ' -A --quiet -l ' + SecondsBetweenDates + ' -u winamp'
    timeout = -1
  }

  console.log("Executing: '" + commando + "'")

  var child = childProcess.exec(commando, {timeout: timeout}, function () {
    console.log('Rip ' + record.id + ' with ' + record.command + ' with PID ' + child.pid + ' ended.')
  })
  console.log('Started Rip ' + record.id + ' with ' + record.command + ' with PID ' + child.pid)
  callback(record, child.pid)
}

function isOnTime (record) {
  var moment = require('moment-timezone')
  var now = moment().tz('Europe/Berlin')
  var rs = moment(record.start).tz('Europe/Berlin')
  if (now.isSame(rs, 'minute')) {
    return true
  } else {
    return false
  }
}
