var TCJ = require('cron').CronJob
var childProcess = require('child_process')
var jsonfile = require('jsonfile')

var cronid = process.env.WORKER_ID
var cron = jsonfile.readFileSync(process.env.WORKER_DATABASE + '/crons/' + cronid + '.json')
var downloads = process.env.WORKER_DOWNLOADS
console.log('Adding Cron ' + cronid + ' with tab ' + cron.tab)

TCJ('00 ' + cron.tab, function () {
  var commando = ''
  var timeout = cron.length
  if (cron.command === 'mplayer') {
    commando = 'mplayer -dumpstream -dumpfile ' + downloads + '/' + cron.times_run + '-' + cron.filename + '_id-' + cronid + '.' + cron.type + ' ' + cron.url
  } else if (cron.command === 'vlc') {
    commando = 'vlc ' + cron.url + ' --sout file/' + cron.type + ':' + downloads + '/' + cron.times_run + '-' + cron.filename + '_id-' + cronid + '.' + cron.type
  } else { // streamripper
    commando = 'streamripper ' + cron.url + ' -a ' + downloads + '/' + cron.times_run + '-' + cron.filename + '_id-' + cronid + ' -A --quiet -l ' + cron.length + ' -u winamp'
    timeout = -1
  }

  console.log("Executing: '" + commando + "'")

  childProcess.exec(commando, {timeout: timeout}, function () {
    cron.times_run++
    var m = {}
    m.type = 'custom'
    m.text = 'reload'
    m.sender = cronid
    process.send(m)
  })
}, null, true, 'Europe/Berlin')

process.on('message', function (msg) {
  if (msg.trim() === 'STOP') {
    console.log('Asked to quit: ' + cronid)
    process.exit()
  }
})
