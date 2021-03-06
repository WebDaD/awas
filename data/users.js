/**
 * DATA Routes for USers
 */
module.exports = {
	load: function(database) {
		var users = [];
		var fs = require('fs');
		var jsonfile = require('jsonfile');
		var files = fs.readdirSync(database + "/users");
		for (var x = 0; x < files.length; x++) {
			var f = database + "/users/" + files[x];
			var stats = fs.statSync(f);
			if (stats.size > 0) {
				var u = jsonfile.readFileSync(f);
				u.id = files[x].replace('.json', '');
				if (typeof u.admin !== "boolean") {
					u.admin = (u.admin === 'true');
				}
				users.push(u);
			}
		}
		return users;
	},
	updateUser: function(database, user, callback) {
		if (!goodUser(user)) {
			return callback({
				status: 418
			});
		}
		if (!hasID(user)) {
			return callback({
				status: 400
			});
		}
		var jsonfile = require('jsonfile');
		var id = user.id;
		delete user.id;
		var file = database + "/users/" + id + ".json";
		user.token = createToken(user);
		jsonfile.writeFile(file, user, function(err) {
			if (err) {
				callback({
					status: 500
				});
			} else {
				user.id = id;

				callback(null, user);
			}
		});
	},
	deleteUser: function(database, id, callback) {
		if (typeof id === 'undefined') {
			return callback({
				status: 400
			});
		}
		var fs = require('fs');
		var file = database + "/users/" + id + ".json";
		fs.unlink(file, function(err) {
			if (err) {
				callback({
					status: 500
				});
			} else {
				callback(null, id);
			}
		});
	},
	createUser: function(database, user, callback) {
		if (!goodUser(user)) {
			return callback({
				status: 418
			});
		}
		var jsonfile = require('jsonfile');
		var shortid = require('shortid');
		var id = shortid.generate();
		var file = database + "/users/" + id + ".json";
		user.token = createToken(user);
		jsonfile.writeFile(file, user, function(err) {
			if (err) {
				callback({
					status: 500
				});
			} else {
				user.id = id;

				callback(null, user);
			}
		});
	},
	checkLogin: function(users, info, callback) { //info={login,pwd}, callback(err,user{token,name})
		var login = false;
		if (users.length !== 0) {
			for (var u = 0; u < users.length; u++) {
				if (users[u].login == info.login) {
					if (users[u].password == info.password) {
						login = true;
						return callback(null, {
							token: users[u].token,
							user: users[u].name,
							admin: users[u].admin
						});
					}
				}
			}
			if (!login) {
				callback({
					status: 401
				});
			}
		} else {
			callback({
				status: 500
			});
		}
	}
};

function goodUser(user) {
	if (typeof user !== 'undefined' &&
		typeof user.name !== 'undefined' &&
		typeof user.login !== 'undefined' &&
		typeof user.email !== 'undefined' &&
		typeof user.password !== 'undefined' &&
		typeof user.admin !== 'undefined'
	) {
		return true;
	} else {
		return false;
	}
}

function hasID(user) {
	if (typeof user.id !== 'undefined') {
		return true;
	} else {
		return false;
	}
}

function createToken(user) {
	var md5 = require('MD5');
	return md5(user.id + user.login + user.password);
}
