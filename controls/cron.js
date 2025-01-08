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

var downloads = conf.downloads
let cron = jsonfile.readFileSync(cronPath)
console.log('Adding Cron ' + cronid + ' with tab ' + cron.tab + ' and length ' + cron.length + ' and commando ' + cron.command)

try {
    const job = new CRON.CronJob(
        cron.tab,
        function() {
            console.log('CRON[' + cronid + '] TICK');
            cron = jsonfile.readFileSync(cronPath);
            let commando = '';
            let timeout = -1; // Timeout duration in seconds

            if (cron.command === 'mplayer') {
                commando = 'mplayer -dumpstream -dumpfile ' + downloads + '/' + cron.times_run + '-' + cron.filename + '_id-' + cronid + '.' + cron.type + ' ' + cron.url;
                //mplayer endpos option is not working for live streams so we use the timeout approach
                timeout = cron.length;
            } else if (cron.command === 'vlc') {
                let run_time_cmd = "--run-time=" + cron.length
                if (cron.type === "ogg") {
                    // there is a bug in vlc with --run-time= - as soon as we use --run-time ogg file is not written to the file anymore
                    // so in this case we don't use the run_time_cmd but kill the process later on. 
                    timeout = cron.length;
                    run_time_cmd = "";
                }
                commando = 'vlc --intf dummy --playlist-autostart --no-playlist-tree ' + run_time_cmd + ' --sout "#duplicate{dst=std{access=file,mux=' + cron.type + ',dst=' + downloads + '/' + cron.times_run + '-' + cron.filename + '_id-' + cronid + '.' + cron.type + '}}" ' + cron.url + ' vlc://quit';

            } else { // streamripper
                commando = 'streamripper ' + cron.url + ' -a ' + downloads + '/' + cron.times_run + '-' + cron.filename + '_id-' + cronid + ' -A --quiet -l ' + cron.length + ' -u winamp';
            }

            console.log('CRON[' + cronid + "]: Executing: '" + commando + "' + Timeout: '" + timeout);

            // Ensure timeout is a valid number even if it's a string like '5'
            if (timeout && typeof timeout === 'string') {
                timeout = parseInt(timeout, 10); // Convert to integer
            }

            // Check if timeout is a valid number
            if (isNaN(timeout) || timeout <= 0) {
                timeout = -1; // Set timeout to 0 (no timeout) if invalid
            }

            // Ensure the timeout is a valid unsigned integer (in milliseconds for exec)
            let options = {};
            if (timeout > 0) {
                options.timeout = timeout * 1000; // Convert timeout to milliseconds
            }

            cron.times_run++;
            jsonfile.writeFileSync(conf.database + '/crons/' + cronid + '.json', cron);

            // Execute the command
            const child = childProcess.exec(commando, options, function(error, stdout, stderr) {
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

            // If timeout is set, forcefully kill the process after the timeout duration
            if (timeout > 0) {
                setTimeout(() => {
                    console.log('CRON[' + cronid + ']: Timeout reached. Killing VLC or command...');
                    child.kill(); // Forcefully terminate the child process
                }, timeout * 1000); // Convert seconds to milliseconds just for `setTimeout`
            }

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