/**
 * DATA Routes for Archived Records
 */
module.exports = {
	load: function(database) {
		var records = [];
		var fs = require('fs');
		var jsonfile = require('jsonfile');
		var files = fs.readdirSync(database + "/archive");
		for (var x = 0; x < files.length; x++) {
			var f = database + "/archive/" + files[x];
			var stats = fs.statSync(f);
			if (stats.size > 0) {
				var r = jsonfile.readFileSync(f);
				r.id = files[x].replace('.json', '');
				records.push(r);
			}
		}
		return records;
	},
	deleteRecord: function(database, id, callback) {
    if(typeof id === 'undefined'){
      return callback({status:400});
    }
		var fs = require('fs');
		var file = database + "/archive/" + id + ".json";
		fs.unlink(file, function(err) {
			if (err) {
				callback({status:500});
			} else {
				callback(null, id);
			}
		});
	}
};
