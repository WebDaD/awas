/**
 * Web Routes for Login
 */
module.exports = function (app, data, functions, users) {
  app.get('/login.html', function (req, res) {
    res.render('login')
  })
  app.post('/login', function (req, res) {
    if (typeof req.body.info === 'undefined') {
      res.sendStatus(400)
    } else {
      users.checkLogin(data.users, req.body.info, function (err, data2) {
        if (err) {
          res.sendStatus(err.status)
        } else {
          var userAgent = req.headers['user-agent']
          var ip = req.headers['x-forwarded-for'] || req.connection.remoteAddress
          console.log(data.admins)
          functions.createEntry(data.loggedIn, userAgent, ip, data2.token, function () {
            if (data2.admin) {
              functions.createAdmin(data.admins, userAgent, ip, data2.token, function () {
                res.status(200).send(data2)
              })
            } else {
              res.status(200).send(data2)
            }
          })
        }
      })
    }
  })
  app.post('/logout', function (req, res) {
    var userAgent = req.headers['user-agent']
    var ip = req.headers['x-forwarded-for'] || req.connection.remoteAddress
    var token = req.headers.token
    functions.removeEntry(data.loggedIn, data.admins, userAgent, ip, token, function () {
      return res.sendStatus(200)
    })
    return res.sendStatus(404)
  })
}
