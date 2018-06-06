/**
 * Main Routes
 */
module.exports = function (app, data, functions) {
  app.get('/favicon.ico', function (req, res) {
    res.sendFile(__dirname + '/public/img/favicon.ico')
  })
  app.get('/manifest.json', function (req, res) {
    res.sendFile(__dirname + '/public/manifest.json')
  })

  app.get('/', functions.isLoggedIn(data.loggedIn), function (req, res) {
    res.render('records', {
      records: data.records,
      archive: false
    })
  })

  app.get('/space.:command(html|free|used|total|downloads|database|pfree)', functions.isLoggedIn(data.loggedIn), function (req, res) {
    var diskspace = require('diskspace')
    var dir = require('dir-util')
    var filesize = require('filesize')
    switch (req.params.command) {
      case 'free':
        diskspace.check('/', function (err, total2, free2, status2) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              return res.send(filesize(free2).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'pfree':
        diskspace.check('/', function (err, total2, free2, status2) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              var percentFree = Math.round((100 * (free2)) / (total2))
              return res.send(filesize(free2).toString() + ' / ' + percentFree.toString() + '%')
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'used':
        diskspace.check('/', function (err, total2, free2, status2) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              var used = (total2) - (free2)
              return res.send(filesize(used).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'total':
        diskspace.check('/', function (err, total2, free2, status2) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              return res.send(filesize(total2).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'downloads':
        dir.getSize(app.downloads, function (err, size) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              return res.send(filesize(size).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'database':
        dir.getSize(app.database, function (err, size) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              return res.send(filesize(size).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'html':
        diskspace.check('/', function (err, total2, free2, status2) {
          dir.getSize(app.downloads, function (err, downloads) {
            dir.getSize(app.database, function (err, database) {
              var percentUsed = Math.round((100 * ((total2) - (free2))) / (total2))
              var percentFree = 100 - percentUsed
              return res.render('space', {
                free: filesize(free2),
                total: filesize(total2),
                used: filesize(((total2) - (free2))),
                downloads: filesize(downloads),
                database: filesize(database),
                percentUsed: percentUsed,
                percentFree: percentFree
              })
            })
          })
        })
        break
      default:
        return res.send(req.params.command + ' not recognized.')
    }
  })
}
