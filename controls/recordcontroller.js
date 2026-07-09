var conf = require('../config.json');
var RECORDS = require('../data/records');
var moment = require('moment');
var CronJob = require('cron').CronJob;
const childProcess = require('child_process');

var records = RECORDS.load(conf.database);

var job = new CronJob('* * * * *', function() {
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

        if (!rec.recording && now.isBetween(startTime, stopTime)) {
            console.log(`✅ Record ${rec.id} is scheduled to start recording.`);
            startRecording(rec, length, now);
        } else {
            console.log(`⏭️ Record ${rec.id} is already recording or outside schedule.`);
        }
    }
}, null, true, 'Europe/Berlin');

console.log("🚀 'RecordControl' running: " + job.running);

function startRecording(rec, length, now) {
    let filename = rec.filename.endsWith('_%D') ? rec.filename : rec.filename + '_%D';
    if (rec.command !== 'streamripper') {
        filename = filename.replace('%D', now.format('YYYY-MM-DD_HH-mm-ss'));
    }
    let filePathRaw = `${conf.downloads}/${filename.trim()}_id-${rec.id}`;
    let filePath = `${filePathRaw}.${rec.type}`;

    let commando = '';
    if (rec.command === 'mplayer') {
        commando = `timeout -s INT -k 30s ${length} mplayer -dumpstream -dumpfile ${filePath} ${rec.url.trim()} -cache 8192 -cache-min 50 -forceidx`;
    } else if (rec.command === 'vlc') {
        commando = `sudo -u vlc timeout -s INT -k 30s ${length} vlc ${rec.url.trim()} --sout file:${filePath} --sout-keep --http-reconnect --network-caching=10000 --rtsp-tcp --no-sout-rtp-sap --no-sout-standard-sap`;
    } else if (rec.command === 'ffmpeg') {
        commando = `timeout -s INT -k 30s ${length} ffmpeg -i ${rec.url.trim()} -c copy ${filePath} -loglevel quiet -reconnect -reconnect_at_eof -reconnect_on_network_error -reconnect_streamed -reconnect_delay_max 10`;
    } else if (rec.command === 'ffmpeg-all') {
        commando = `timeout -s INT -k 30s ${length} ffmpeg -i ${rec.url.trim()} -c copy -map 0 ${filePath} -loglevel quiet -reconnect -reconnect_at_eof -reconnect_on_network_error -reconnect_streamed -reconnect_delay_max 10`;
    } else if (rec.command === 'streamlink-hls-dash') {
        commando = `timeout -s INT -k 30s ${length} streamlink "${rec.url.trim()}" best --output "${filePath}" --force --quiet --retry-streams 3 --retry-max 9999 --retry-open 9999 --stream-segment-attempts 9999 --stream-segment-timeout 60.0 --stream-timeout 3600.00`;
    } else if (rec.command === 'streamlink-http') {
        commando = `timeout -s INT -k 30s ${length} streamlink "httpstream://${rec.url.trim()}" best --output "${filePath}" --force --quiet --retry-streams 3 --retry-max 9999 --retry-open 9999 --stream-segment-attempts 9999 --stream-segment-timeout 60.0 --stream-timeout 3600.00`;
    } else if (rec.command === 'yt-dlp') {
        commando = `timeout -s INT -k 30s ${length} yt-dlp "${rec.url.trim()}" --output "${filePath}" --no-abort-on-error --socket-timeout 3600 --file-access-retries infinite --fragment-retries infinite --hls-use-mpegts --no-part --quiet`;
    } else if (rec.command === 'yt-dlp-ffmpeg') {
        commando = `timeout -s INT -k 30s ${length} yt-dlp "${rec.url.trim()}" --output "${filePath}" --no-abort-on-error --socket-timeout 3600 --file-access-retries infinite --fragment-retries infinite --downloader ffmpeg --hls-use-mpegts --no-part --quiet`;
    } else {
        commando = `timeout -s INT -k 30s ${length} streamripper ${rec.url.trim()} -a ${filePathRaw} -A --quiet -u winamp`;
    }

    console.log(`🚀 Starting recording: '${commando}'`);

    // Mark as recording before starting the process
    rec.recording = true;
    RECORDS.updateRecord(conf.database, rec);

    let process = childProcess.exec(commando, {}, function(error, stdout, stderr) {
        if (error) {
            console.error(`❌ Error executing command for record ${rec.id}: ${error.message}`);
            console.error(`📛 Stderr: ${stderr}`);
            rec.recording = false;
            rec.pid = null;
            RECORDS.updateRecord(conf.database, rec);
            return;
        }
        console.log(`🎙️ Recording started for record ${rec.id}: ${stdout}`);
    });

    // Assign PID only when the process has started
    process.on('spawn', () => {
        rec.pid = process.pid;

        RECORDS.updateRecord(conf.database, rec, function(error) {
            if (error) {
                console.error("❌ Failed to update record:", error);
            } else {
                console.log(`✅ Record ${rec.id} marked as recording with PID ${rec.pid}.`);
            }
        });
    });
}
