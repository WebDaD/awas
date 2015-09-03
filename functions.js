module.exports = {
	containsObject: function(obj, list) {
		var i;
		if (obj === null || typeof list === 'undefined' || typeof list.length === 'undefined') {
			return false;
		}

		for (i = 0; i < list.length; i++) {
			if (list[i] === obj) {
				return true;
			}
		}
		return false;
	},
	getUserFromRequest: function(req, writing) {
		var md5 = require('MD5');
		var user_agent = req.headers['user-agent'];
		var ip = req.headers['x-forwarded-for'] || req.connection.remoteAddress;
		if (writing) {
			var token = req.headers.token;
			return md5(user_agent + token + ip);
		} else {
			return md5(user_agent + ip);
		}
	},
	isLoggedIn: function(users, writing) {
		return function(req, res, next) {
			var user = module.exports.getUserFromRequest(req, writing);
			if (module.exports.containsObject(user, users)) {
				next();
			} else {
				if (writing) {
					res.sendStatus(401);
				} else {
					res.redirect(302, 'login.html');
				}

			}
		};
	},
	isAdmin: function(admins, writing) {
		return function(req, res, next) {
			var user = module.exports.getUserFromRequest(req, writing);
			if (module.exports.containsObject(user, admins)) {
				req.admin = true;
			} else {
				req.admin = false;
			}
			next();
		};
	},
	createEntry: function(loggedIn, user_agent, ip, token, callback) {
		var md5 = require('MD5');
		loggedIn.push(md5(user_agent + token + ip));
		loggedIn.push(md5(user_agent + ip));
		callback();
	},
	createAdmin: function(admins, user_agent, ip, token, callback) {
		var md5 = require('MD5');
		admins.push(md5(user_agent + token + ip));
		admins.push(md5(user_agent + ip));
		callback();
	},
	removeEntry: function(loggedIn, admins, user_agent, ip, token, callback) {
		var md5 = require('MD5');
		var t1 = md5(user_agent + token + ip);
		var t2 = md5(user_agent + ip)
		var index1 = loggedIn.indexOf(t1);
		if (index1 > -1) {
			loggedIn.splice(index1, 1);
		}
		var index2 = loggedIn.indexOf(t2);
		if (index2 > -1) {
			loggedIn.splice(index2, 1);
		}
		var index3 = admins.indexOf(t1);
		if (index3 > -1) {
			admins.splice(index3, 1);
		}
		var index4 = admins.indexOf(t2);
		if (index4 > -1) {
			admins.splice(index4, 1);
		}
		callback();
	}
};
