var conf = require('../config.json');
var RECORDS = require('../data/records');
var moment = require('moment');
var CronJob = require('cron').CronJob;
const childProcess = require('child_process');

var records = RECORDS.load(conf.database);

var job = new CronJob('* * * * *', function() { // Runs every minute
    console.log('🔄 RC TICK - Checking for recordings');

    records = RECORDS.load(conf.database);
    console.log(`📋 Loaded ${records.length} records`);

    if (records.length === 0) {
        console.log("❌ No records found");
        return;
    }

    for (let r = 0; r < records.length; r++) {
        let rec = records[r];

        if (typeof rec.recording === 'undefined') {
            rec.recording = false;
            console.log(`🛠 Fixed missing 'recording' status for record ${rec.id}, setting to false.`);
        }

        let now = moment();
        let startTime = moment(rec.start);
        let stopTime = moment(rec.stop);
        let length = moment.duration(stopTime.diff(startTime)).asSeconds();

        console.log(`🔍 Checking record ${rec.id}: recording=${rec.recording}, pid=${rec.pid || "none"}, now=${now.format()}, start=${startTime.format()}, stop=${stopTime.format()}`);

        // Check if the recording is already running by verifying the PID
        if (rec.recording && rec.pid) {
            let checkProcessCmd = `ps -p ${rec.pid} -o comm=`;

            childProcess.exec(checkProcessCmd, function(error, stdout) {
                if (!error && stdout.trim().includes("streamripper")) {
                    console.log(`⚠️ Record ${rec.id} is already running with PID ${rec.pid}. Skipping.`);
                    return;
                }

                console.log(`🛠 Process ${rec.pid} not found. Marking record as stopped.`);
                rec.recording = false;
                rec.pid = null;
                RECORDS.updateRecord(conf.database, rec);
            });
        }

        // Start new recording only if it's not already running
        if (!rec.recording && now.isBetween(startTime, stopTime)) {
            console.log(`✅ Record ${rec.id} is scheduled to start recording.`);
            startRecording(rec, length, now);
        } else {
            console.log(`⏭️ Record ${rec.id} is already recording or outside schedule.`);
        }
    }
}, null, true, 'Europe/Berlin');

console.log("🚀 'RecordControl' running: " + job.running);

/**
 * Starts a recording session.
 */
function startRecording(rec, length, now) {
    const formattedDateTime = now.format('YYYY-MM-DD_HH-mm-ss');
    let filename = rec.filename.replace('%D', formattedDateTime);
    let filePath = `${conf.downloads}/${filename.trim()}_id-${rec.id}.${rec.type}`;

    let commando = `timeout ${length} streamripper ${rec.url.trim()} -a ${filePath} -A --quiet -u winamp`;

    console.log("🚀 Starting recording: '" + commando + "'");

    let options = {};
    let process = childProcess.exec(commando, options, function(error, stdout, stderr) {
        if (error) {
            console.error(`❌ Error executing command for record ${rec.id}: ${error.message}`);
            console.error(`📛 Stderr: ${stderr}`);
            return;
        }
        console.log(`🎙️ Recording started for record ${rec.id}: ${stdout}`);
    });

    // Save the process ID (PID) to avoid duplicate recordings
    rec.recording = true;
    rec.pid = process.pid;

    RECORDS.updateRecord(conf.database, rec, function(error) {
        if (error) {
            console.error("❌ Failed to update record:", error);
        } else {
            console.log(`✅ Record ${rec.id} marked as recording with PID ${rec.pid}.`);
        }
    });
}