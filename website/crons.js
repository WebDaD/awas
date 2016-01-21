/**
 * Web Routes for Records
 */
module.exports = function(app, data, functions,crons, cronripper) {
  app.get('/crons.html',functions.isLoggedIn(data.loggedIn),functions.isAdmin(data.admins), function(req, res) {
				res.render("crons", {crons:data.crons, admin:req.admin});
	});
  app.get('/active_crons', function(req, res) {
    var count = 0;
    data.crons.forEach(function(element){
      if(isActive(element)){
        count++;
      }
    });
    res.send(count.toString());
	});
  app.post('/crons', functions.isLoggedIn(data.loggedIn,true), function(req, res) {
    if(typeof req.body.cron === 'undefined'){
      res.sendStatus(400);
    } else {
      crons.createCron(app.database,req.body.cron, function(err,result){
        if(err){
          res.sendStatus(err.status);
        } else {
          data.crons.push(result);
          cronripper.load(app, data, crons);
          res.sendStatus(201);
        }
      });
    }
  });
  app.put('/crons/:id', functions.isLoggedIn(data.loggedIn,true), function(req, res) {
    if(typeof req.body.cron === 'undefined' || typeof req.params.id === 'undefined'){
      res.sendStatus(400);
    } else {
      var cron = req.body.cron;
      cron.id = req.params.id;
      crons.updateCron(app.database,cron, function(err,result){
        if(err){
          res.sendStatus(err.status);
        } else {
          for(var u=0;u<data.crons.length;u++){
            if(data.crons[u].id == result.id){
              data.crons[u] = result;
            }
          }
          cronripper.load(app, data, crons);
          res.sendStatus(200);
        }
      });
    }
  });
  app.delete('/crons/:id', functions.isLoggedIn(data.loggedIn,true), function(req, res) {
    if(typeof req.params.id === 'undefined'){
      res.sendStatus(400);
    } else {
      crons.deleteCron(app.database,req.params.id, function(err,result){
        if(err){
          res.sendStatus(err.status);
        } else {
          var index = -1;
          for(var u=0;u<data.crons.length;u++){
            if(data.crons[u].id == result){
              index = u;
            }
          }
          if (index > -1) {
              data.crons.splice(index, 1);
          }
          cronripper.load(app, data, crons);
          res.sendStatus(200);
        }
      });
    }
  });
};
