/**
 * Web Routes for USers
 */
module.exports = function(app, data, functions, users) {
	app.get('/users.html', functions.isLoggedIn(data.loggedIn), function(req, res) {
		res.render("users", {
			users: data.users,
			admin: true //TODO:cleanup!
		});
	});
  app.post('/users', functions.isLoggedIn(data.loggedIn,true), function(req, res) {
    if(typeof req.body.user === 'undefined'){
      res.sendStatus(400);
    } else {
      users.createUser(app.database,req.body.user, function(err,result){
        if(err){
          res.sendStatus(err.status);
        } else {
          data.users.push(result);
          res.sendStatus(201);
        }
      });
    }
  });
  app.put('/users/:id', functions.isLoggedIn(data.loggedIn,true), function(req, res) {
    if(typeof req.body.user === 'undefined' || typeof req.params.id === 'undefined'){
      res.sendStatus(400);
    } else {
      var user = req.body.user;
      user.id = req.params.id;
      users.updateUser(app.database,user, function(err,result){
        if(err){
          res.sendStatus(err.status);
        } else {
          for(var u=0;u<data.users.length;u++){
            if(data.users[u].id == result.id){
              data.users[u] = result;
            }
          }
          res.sendStatus(200);
        }
      });
    }
  });
  app.delete('/users/:id', functions.isLoggedIn(data.loggedIn,true), function(req, res) {
    if(typeof req.params.id === 'undefined'){
      res.sendStatus(400);
    } else {
      users.deleteUser(app.database,req.params.id, function(err,result){
        if(err){
          res.sendStatus(err.status);
        } else {
          var index = -1;
          for(var u=0;u<data.users.length;u++){
            if(data.users[u].id == result){
              index = u;
            }
          }
          if (index > -1) {
              data.users.splice(index, 1);
          }
          res.sendStatus(200);
        }
      });
    }
  });
};
