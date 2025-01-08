var conf = require('../config.json')
var RECORDS = require('../data/records')
var moment = require('moment')
var CronJob = require('cron').CronJob
const childProcess = require('child_process')
var records = RECORDS.load(conf.database)

var job = new CronJob('* * * * *', function() { // eslint-disable-line no-unused-vars
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
                let commando = ''
                let timeout = -1
                if (rec.command === 'mplayer') {
                    commando = 'mplayer -dumpstream -dumpfile ' + conf.downloads + '/' + rec.filename.trim() + '_id-' + rec.id + '.' + rec.type + ' ' + rec.url.trim()
                        //mplayer endpos option is not working for live streams so we use the timeout approach
                    timeout = length;
                } else if (rec.command === 'vlc') {
                    let run_time_cmd = "--run-time=" + length
                    if (rec.type === "ogg") {
                        // there is a bug in vlc with --run-time= - as soon as we use --run-time ogg file is not written to the file anymore
                        // so in this case we don't use the run_time_cmd but kill the process later on. 
                        timeout = length;
                        run_time_cmd = "";
                    }
                    commando = 'vlc --intf dummy --playlist-autostart --no-playlist-tree ' + run_time_cmd + ' --sout "#duplicate{dst=std{access=file,mux=' + rec.type + ',dst=' + conf.downloads + '/' + rec.filename.trim() + '_id-' + rec.id + '.' + rec.type + '}}" ' + rec.url.trim() + ' vlc://quit';
                } else { // streamripper
                    commando = 'streamripper ' + rec.url.trim() + ' -a ' + conf.downloads + '/' + rec.filename.trim() + '_id-' + rec.id + ' -A --quiet -l ' + length + ' -u winamp'
                }

                // Ensure timeout is a valid number even if it's a string like '5'
                if (timeout && typeof timeout === 'string') {
                    timeout = parseInt(timeout, 10); // Convert to integer
                }

                // Check if timeout is a valid number
                if (isNaN(timeout) || timeout <= 0) {
                    timeout = -1; // Set timeout to 0 (no timeout) if invalid
                }

                console.log("RC: Executing: '" + commando + "' - Timeout: " + timeout)
                var options = {}
                if (timeout > 0) {
                    options.timout = timeout
                }
                const child = childProcess.exec(commando, options, function() {
                    var m = {}
                    m.type = 'custom'
                    m.text = 'reload'
                    m.sender = rec.id
                });
                // If timeout is set, forcefully kill the process after the timeout duration
                if (timeout > 0) {
                    setTimeout(() => {
                        console.log('Timeout reached. Killing recording command...');
                        child.kill(); // Forcefully terminate the child process
                    }, timeout * 1000); // Convert seconds to milliseconds just for `setTimeout`
                }
                setTimeout(function() {
                    childProcess.exec("pgrep -f \"" + commando + "\"", options, function(error, stdout) {
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