var conf = require('../config.json')
var jsonfile = require('jsonfile')
var CronJob = require('cron').CronJob
const childProcess = require('child_process')
var http = require('http')
var httpOptions = {
  host: 'localhost',
  path: '/crons/reload',
  method: 'PUT'
}
var httpReq = http.request(httpOptions, function (res) {
  var responseString = ''

  res.on('data', function (data) {
    responseString += data
      // save all the data from response
  })
  res.on('end', function () {
    console.log(responseString)
      // print to console when response ends
  })
})
console.log('Worker Starting...')
var cronid = process.argv[2]
var cron = jsonfile.readFileSync(conf.database + '/crons/' + cronid + '.json')
var downloads = conf.downloads
console.log('Adding Cron ' + cronid + ' with tab ' + cron.tab + ' and length ' + cron.length + ' and commando ' + cron.command)

var job = new CronJob('00 ' + cron.tab, function () { // eslint-disable-line no-unused-vars
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

  console.log("CRON: Executing: '" + commando + "'")

  var options = {}
  if (timeout > 0) {
    options.timout = timeout
  }
  childProcess.exec(commando, options, function () {
    cron.times_run++
    jsonfile.writeFileSync(conf.database + '/crons/' + cronid + '.json', cron)
    httpReq.write()
    httpReq.end()
  })
}, null, true, 'Europe/Berlin')

process.on('stop', function (msg) {
  console.log('Asked to quit: ' + cronid)
  process.exit()
})
