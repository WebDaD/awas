module.exports = {
	containsObject: function(obj, list) {
    var i;
		if(obj === null || typeof list === 'undefined' || typeof list.length === 'undefined'){return false;}

    for (i = 0; i < list.length; i++) {
        if (list[i] === obj) {
            return true;
        }
    }
    return false;
},
getUserFromRequest: function (req){
	//TODO: use token in header, user_agent, ip_adress
	return "1";
},
isLoggedIn: function(users, writing){
	return function(req, res, next) {
		var user = module.exports.getUserFromRequest(req);
		if(module.exports.containsObject(user,users)){
			 next();
		} else {
			if(writing){
				res.sendStatus(401);
			} else{
				res.redirect(401,'login.html');
			}

		}
  };
}
};
