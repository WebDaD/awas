var conf = require('../config.json')
var USER = require('../data/users')
var ftpd = require('ftpd')
var fs = require('fs')
var md5 = require('MD5')
var ip = require('ip')

var users = USER.load(conf.database)

var options = {
  pasvPortRangeStart: 4000,
  pasvPortRangeEnd: 5000,
  getInitialCwd: function (connection, callback) {
    var userPath = conf.downloads
    fs.access(userPath, function (error) {
      if (error) {
        callback('path does not exist', userPath) // eslint-disable-line standard/no-callback-literal
      } else {
        callback(null, userPath)
      }
    })
  },
  getRoot: function (user) {
    return '/'
  }
}

var host = ip.address()

var ftpserver = new ftpd.FtpServer(host, options)

ftpserver.on('error', function (error) {
  console.log('FTP Server error:', error)
})
ftpserver.on('client:connected', function (conn) {
  var username
  console.log('FTP-Client connected from ' + conn.socket.remoteAddress)
  conn.on('command:user', function (user, success, failure) {
    username = user

    var userExists = false
    for (var u = 0; u < users.length; u++) {
      if (users[u].login === username) {
        userExists = true
        break
      }
    }
    if (userExists) {
      success()
    } else {
      failure()
    }
  })
  conn.on('command:pass', function (pass, success, failure) {
    for (var u = 0; u < users.length; u++) {
      if (users[u].login === username) {
        if (users[u].password === md5(pass)) {
          return success(username)
        }
      }
    }
    failure()
  })
})
ftpserver.listen(conf.ftp_port)
console.log('FTPD listening on port ' + conf.ftp_port)
