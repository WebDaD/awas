const conf = require('../config.json');
const CRONS = require('../data/crons');
const CronJob = require('cron').CronJob;
const pm2 = require('pm2');
const childprogram = '../awas/controls/cron.js';

// Function to calculate a simple hash of a cron job configuration
function hashCronConfig(cron) {
    const { times_run, ...filteredCron } = cron; // Remove times_run
    return JSON.stringify(filteredCron); // Simple hash based on JSON string
}

// Track active crons and their configurations
let activeCrons = new Map(); // Map of cronId to config hash
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
        startCron(cron);
    }
}

// Function to start or restart a specific cron by ID
function startCron(cron) {
    const cronId = cron.id;
    const cronHash = hashCronConfig(cron);

    if (activeCrons.has(cronId) && activeCrons.get(cronId) === cronHash) {
        console.log(`Worker CRON_${cronId} is already running with the same configuration.`);
        return;
    }

    // If the cron is already running with a different config, stop it first
    if (activeCrons.has(cronId)) {
        console.log(`Restarting Worker CRON_${cronId} due to configuration change.`);
        stopCron(cronId);
    } else {
        console.log('Starting Worker ' + cronId);
    }

    // Start the cron with the new configuration
    pm2.start({
            script: childprogram,
            name: 'CRON_' + cronId,
            args: cronId,
        },
        function(err, apps) {
            if (err) {
                console.error(`Failed to start CRON_${cronId}:`, err);
            } else {
                activeCrons.set(cronId, cronHash);
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

            // Start or restart crons with updated configurations
            for (const cron of crons) {
                startCron(cron);
            }
        }, 15000); // Delay 15 seconds
    },
    null,
    true,
    'Europe/Berlin'
);

console.log("'CronControl' running: " + job.running);