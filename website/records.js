/**
 * Web Routes for Records
 */
module.exports = function (app, data, functions, records, archive, ipc) {
  app.get('/records.html', functions.isLoggedIn(data.loggedIn), functions.isAdmin(data.admins), function (req, res) {
    res.render('records', {records: data.records, archive: false, admin: req.admin})// TODO: clean admin
  })
  app.get('/archive.html', functions.isLoggedIn(data.loggedIn), functions.isAdmin(data.admins), function (req, res) {
    res.render('records', {records: data.archive, archive: true, admin: req.admin}) // TODO: clean admin
  })
  app.get('/active_records', function (req, res) {
    var count = 0
    data.records.forEach(function (element) {
      if (isActive(element)) {
        count++
      }
    })
    res.send(count.toString())
  })
  app.post('/records', functions.isLoggedIn(data.loggedIn, true), function (req, res) {
    if (typeof req.body.record === 'undefined') {
      res.sendStatus(400)
    } else {
      records.createRecord(app.database, req.body.record, function (err, result) {
        if (err) {
          res.sendStatus(err.status)
        } else {
          data.records.push(result)
          res.sendStatus(201)
        }
      })
    }
  })
  app.post('/records/:id/stop', functions.isLoggedIn(data.loggedIn, true), function (req, res) {
    if (typeof req.params.id === 'undefined') {
      res.sendStatus(400)
    } else {
      records.stopRecord(app.database, req.params.id, function (err, result) {
        if (err) {
          res.sendStatus(err.status)
        } else {
          for (var u = 0; u < data.records.length; u++) {
            if (data.records[u].id === result.id) {
              data.records[u] = result
            }
          }
          res.sendStatus(200)
        }
      })
    }
  })
  app.put('/records/:id', functions.isLoggedIn(data.loggedIn, true), function (req, res) {
    if (typeof req.body.record === 'undefined' || typeof req.params.id === 'undefined') {
      res.sendStatus(400)
    } else {
      var record = req.body.record
      record.id = req.params.id
      records.updateRecord(app.database, record, function (err, result) {
        if (err) {
          res.sendStatus(err.status)
        } else {
          for (var u = 0; u < data.records.length; u++) {
            if (data.records[u].id === result.id) {
              data.records[u] = result
            }
          }
          res.sendStatus(200)
        }
      })
    }
  })
  app.delete('/records/:id', functions.isLoggedIn(data.loggedIn, true), function (req, res) {
    if (typeof req.params.id === 'undefined') {
      res.sendStatus(400)
    } else {
      records.deleteRecord(app.database, req.params.id, function (err, result) {
        if (err) {
          res.sendStatus(err.status)
        } else {
          var index = -1
          for (var u = 0; u < data.records.length; u++) {
            if (data.records[u].id === result) {
              index = u
            }
          }
          if (index > -1) {
            data.records.splice(index, 1)
          }
          res.sendStatus(200)
        }
      })
    }
  })
  app.delete('/archive/:id', functions.isLoggedIn(data.loggedIn, true), function (req, res) {
    if (typeof req.params.id === 'undefined') {
      res.sendStatus(400)
    } else {
      archive.deleteRecord(app.database, req.params.id, function (err, result) {
        if (err) {
          res.sendStatus(err.status)
        } else {
          var index = -1
          for (var u = 0; u < data.archive.length; u++) {
            if (data.archive[u].id == result) {
              index = u
            }
          }
          if (index > -1) {
            data.archive.splice(index, 1)
          }
          res.sendStatus(200)
        }
      })
    }
  })
}
function isActive (record) {
  var moment = require('moment-timezone')
  var now = moment()
  var ra = moment(record.start)
  var rs = moment(record.stop)
  if (now.isBetween(ra, rs)) {
    return true
  } else {
    return false
  }
}
