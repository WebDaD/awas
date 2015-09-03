/**
 * Routes for Streamripper
 */
module.exports = function(app) {
	var CronJob3 = require('cron').CronJob;


	new CronJob3('00 * * * * *', function() {
		clean(app);
	}, null, true, 'Europe/Berlin');

	console.log("Cronjob 'DL-Cleaner' running");
};

function clean(app) {
	var fs = require('fs');
	var path = require('path');
	fs.readdir(app.downloads,function(err,files){
    if(err) throw err;
    files.forEach(function(file){
        var ext = path.extname(file);
				if(ext == ".cue"){
					console.log("Deleting "+file);
					fs.unlinkSync(path.join(app.downloads,file));
				}
    });
 });
}
