var conf = require('../config.json');
var jsonfile = require('jsonfile');
var CRON = require('cron');
const childProcess = require('child_process');
var http = require('http');
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

            // Generate current date and time string
            const now = new Date();
            const formattedDateTime = now.toISOString().replace(/T/, '_').replace(/:/g, '-').split('.')[0];

            // Replace `%D` in filename with the current date and time
            let filename = cron.filename.replace('%D', formattedDateTime);

            let commando = '';
            let options = {};
            if (cron.command === 'mplayer') {
                commando = 'timeout ' + cron.length + ' mplayer -dumpstream -dumpfile ' + downloads + '/' + cron.times_run + '-' + filename + '_id-' + cronid + '.' + cron.type + ' ' + cron.url;
            } else if (cron.command === 'vlc') {
                // Run VLC as the 'vlc' user
                commando = 'sudo -u vlc timeout ' + cron.length + ' vlc ' + cron.url + ' --sout file:' + downloads + '/' + cron.times_run + '-' + filename + '_id-' + cronid + '.' + cron.type + ' --sout-keep';
            } else { // streamripper
                commando = 'timeout ' + cron.length + ' streamripper ' + cron.url + ' -a ' + downloads + '/' + cron.times_run + '-' + filename + '_id-' + cronid + ' -A --quiet -u winamp';
            }

            console.log('CRON[' + cronid + "]: Executing: '" + commando);

            cron.times_run++;
            jsonfile.writeFileSync(conf.database + '/crons/' + cronid + '.json', cron);

            // Execute the command
            childProcess.exec(commando, options, function(error, stdout, stderr) {
                // Log the standard output and error for debugging
                console.log('CRON[' + cronid + ']: Standard Output:', stdout);
                console.log('CRON[' + cronid + ']: Standard Error:', stderr);

                // Log error if there is any
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
            // save all the data from response
        });
        res.on('end', function() {
            console.log(responseString);
            // print to console when response ends
        });
    });
    httpReq.write('');
    httpReq.end();
}