const conf = require('../config.json');
const CRONS = require('../data/crons');
const CronJob = require('cron').CronJob;
const pm2 = require('pm2');
const childprogram = '../awas/controls/cron.js';

let activeCrons = new Set(); // Track active crons
let crons = CRONS.load(conf.database) || []; // Ensure array

// Connect to PM2
pm2.connect(function(err) {
    if (err) {
        console.error("Failed to connect to PM2:", err);
        process.exit(2);
    } else {
        startAllCrons(crons);
    }
});

// Function to start all initial crons
function startAllCrons(crons) {
    for (const cron of crons) {
        startCron(cron.id);
    }
}

// Function to start a specific cron by ID
function startCron(cronId) {
    if (activeCrons.has(cronId)) {
        console.log(`Worker CRON_${cronId} is already running.`);
        return;
    }
    console.log('Starting Worker ' + cronId);
    pm2.start({
            script: childprogram,
            name: 'CRON_' + cronId,
            args: cronId,
        },
        function(err, apps) {
            if (err) {
                console.error(`Failed to start CRON_${cronId}:`, err);
            } else {
                activeCrons.add(cronId);
                console.log(`Successfully started CRON_${cronId}.`);
            }
        }
    );
}

// Function to stop a specific cron by ID
function stopCron(cronId) {
    if (!activeCrons.has(cronId)) {
        console.log(`Worker CRON_${cronId} is not running.`);
        return;
    }
    console.log('Stopping Worker ' + cronId);
    pm2.delete('CRON_' + cronId, function(err) {
        if (err) {
            console.error(`Failed to stop CRON_${cronId}:`, err);
        } else {
            activeCrons.delete(cronId);
            console.log(`Successfully stopped CRON_${cronId}.`);
        }
    });
}

// Check for updates every minute
var job = new CronJob(
    '* * * * *',
    function() {
        setTimeout(() => {
            const oldCrons = crons || []; // Fallback to empty array
            crons = CRONS.load(conf.database) || []; // Reload crons
            console.log(`CC TICK (${crons.length} Crons), old length: ${oldCrons.length}`);

            // Stop old crons no longer active
            for (const oldCron of oldCrons) {
                if (!crons.some((cron) => cron.id === oldCron.id)) {
                    stopCron(oldCron.id);
                }
            }

            // Start new crons not currently running
            for (const cron of crons) {
                if (!activeCrons.has(cron.id)) {
                    startCron(cron.id);
                }
            }
        }, 15000); // Delay 15 seconds
    },
    null,
    true,
    'Europe/Berlin'
);

console.log("'CronControl' running: " + job.running);