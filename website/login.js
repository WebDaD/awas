/**
 * Web Routes for Login
 */
module.exports = function(app, data) {
  app.get('/login.html', function(req, res) {
    res.render('login');
  });
};
