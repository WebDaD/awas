var conf = require('../config.json');
var jsonfile = require('jsonfile');
var CRON = require('cron');
const childProcess = require('child_process');
var http = require('http');
const moment = require('moment-timezone');

var httpOptions = {
    port: 8080,
    host: 'localhost',
    path: '/crons/reload',
    method: 'PUT'
};

var cronid = process.argv[2];
console.log('Worker ' + cronid + ' Starting...');
const cronPath = (conf.database + '/crons/' + cronid + '.json').replace(/\/+/g, '/');

var downloads = conf.downloads;
let cron = jsonfile.readFileSync(cronPath);
console.log('Adding Cron ' + cronid + ' with tab ' + cron.tab + ' and length ' + cron.length + ' and commando ' + cron.command);

try {
    const job = new CRON.CronJob(
        cron.tab,
        function() {
            console.log('CRON[' + cronid + '] TICK');
            cron = jsonfile.readFileSync(cronPath);

            let filename = cron.filename.endsWith('_%D') ? cron.filename : cron.filename + '_%D';
            if (cron.command !== 'streamripper') {
                // Generate current date and time string in Germany timezone
                const formattedDateTime = moment().tz('Europe/Berlin').format('YYYY-MM-DD_HH-mm-ss');
                filename = filename.replace('%D', formattedDateTime);
            }
            let commando = '';
            let options = {};
            if (cron.command === 'mplayer') {
                commando = 'timeout ' + cron.length + ' mplayer -dumpstream -dumpfile ' + downloads + '/' + filename + '_id-' + cronid + '.' + cron.type + ' ' + cron.url;
            } else if (cron.command === 'vlc') {
                commando = 'sudo -u vlc timeout ' + cron.length + ' vlc ' + cron.url + ' --sout file:' + downloads + '/' + filename + '_id-' + cronid + '.' + cron.type + ' --sout-keep';
            } else if (cron.command === 'ffmpeg') {
                commando = 'timeout ' + cron.length + ' ffmpeg -i ' + cron.url + ' -c copy ' + downloads + '/' + filename + '_id-' + cronid + '.' + cron.type;
            } else if (cron.command === 'ffmpeg-all') {
                commando = 'timeout ' + cron.length + ' ffmpeg -i ' + cron.url + ' -c copy -map 0 ' + downloads + '/' + filename + '_id-' + cronid + '.' + cron.type;
            } else { // streamripper
                commando = 'timeout ' + cron.length + ' streamripper ' + cron.url + ' -a ' + downloads + '/' + filename + '_id-' + cronid + '.' + cron.type + ' -A --quiet -u winamp';
            }

            console.log('CRON[' + cronid + "]: Executing: '" + commando);
            cron.times_run++;
            jsonfile.writeFileSync(conf.database + '/crons/' + cronid + '.json', cron);

            // Execute the command
            childProcess.exec(commando, options, function(error, stdout, stderr) {
                console.log('CRON[' + cronid + ']: Standard Output:', stdout);
                console.log('CRON[' + cronid + ']: Standard Error:', stderr);
                if (error) {
                    console.log('CRON[' + cronid + ']: Error:', error);
                }
                console.log('CRON[' + cronid + ']: Done.');
                writeHTTP();
            });
        },
        null, // onComplete
        true // start
    );
    console.log('Worker ' + cronid + ' running: ' + job.running);
} catch (ex) {
    console.log('Worker ' + cronid + ' NOT running: Cron Error ' + ex);
}

function writeHTTP() {
    var httpReq = http.request(httpOptions, function(res) {
        var responseString = '';
        res.on('data', function(data) {
            responseString += data;
        });
        res.on('end', function() {
            console.log(responseString);
        });
    });
    httpReq.write('');
    httpReq.end();
}