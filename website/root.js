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
        diskspace.check('/', function (err, total) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              return res.send(filesize.filesize(total.free).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'pfree':
        diskspace.check('/', function (err, total) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              var percentFree = Math.round((100 * (total.free)) / (total.total))
              return res.send(filesize.filesize(total.free).toString() + ' / ' + percentFree.toString() + '%')
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'used':
        diskspace.check('/', function (err, total) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              var used = (total.total) - (total.free)
              return res.send(filesize.filesize(used).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'total':
        diskspace.check('/', function (err, total) {
          if (err) {
            return res.send('ERR')
          } else {
            try {
              return res.send(filesize.filesize(total.total).toString())
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
              return res.send(filesize.filesize(size).toString())
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
              return res.send(filesize.filesize(size).toString())
            } catch (err) {
              return res.send('ERR')
            }
          }
        })
        break
      case 'html':
        diskspace.check('/', function (err, total) {
          dir.getSize(app.downloads, function (err, downloads) {
            dir.getSize(app.database, function (err, database) {
              var percentUsed = Math.round((100 * ((total.total) - (total.free))) / (total.total))
              var percentFree = 100 - percentUsed
              return res.render('space', {
                free: filesize.filesize(total.free),
                total: filesize.filesize(total.total),
                used: filesize.filesize(((total.total) - (total.free))),
                downloads: filesize.filesize(downloads),
                database: filesize.filesize(database),
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
