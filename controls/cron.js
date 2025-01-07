var conf = require('../config.json')
var jsonfile = require('jsonfile')
var CRON = require('cron')
const childProcess = require('child_process')
var http = require('http')
var httpOptions = {
    host: 'localhost',
    path: '/crons/reload',
    method: 'PUT'
}

var cronid = process.argv[2]
console.log('Worker ' + cronid + ' Starting...')
const cronPath = (conf.database + '/crons/' + cronid + '.json').replace(/\/+/g, '/')
var cron = jsonfile.readFileSync(cronPath)

var downloads = conf.downloads
console.log('Adding Cron ' + cronid + ' with tab ' + cron.tab + ' and length ' + cron.length + ' and commando ' + cron.command)

try {
    var job = new CRON.CronJob({
        cronTime: cron.tab,
        onTick: function() {
            console.log('CRON[' + cronid + ' TICK')
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

            console.log('CRON[' + cronid + "]: Executing: '" + commando + "'")

            var options = {}
            if (timeout > 0) {
                options.timout = timeout
            }
            childProcess.exec(commando, options, function() {
                cron.times_run++
                    jsonfile.writeFileSync(conf.database + '/crons/' + cronid + '.json', cron)
                console.log('CRON[' + cronid + ']: Done.')
                writeHTTP()
            })
        },
        start: true,
        timeZone: 'Europe/Berlin'
    })
} catch (ex) {
    console.log('Worker ' + cronid + ' NOT running: Cron Pattern ' + cron.tab + ' not valid!')
}
console.log('Worker ' + cronid + ' running: ' + job.running)

function writeHTTP() {
    var httpReq = http.request(httpOptions, function(res) {
        var responseString = ''

        res.on('data', function(data) {
            responseString += data
                // save all the data from response
        })
        res.on('end', function() {
            console.log(responseString)
                // print to console when response ends
        })
    })
    httpReq.write('')
    httpReq.end()
}