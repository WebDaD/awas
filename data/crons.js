/**
 * DATA Routes for Records
 */
module.exports = {
  load: function (database) {
    var crons = []
    var fs = require('fs')
    var jsonfile = require('jsonfile')
    var files = fs.readdirSync(database + '/crons')
    for (var x = 0; x < files.length; x++) {
      var f = database + '/crons/' + files[x]
      var stats = fs.statSync(f)
      if (stats.size > 0) {
        var c = jsonfile.readFileSync(f)
        c.id = files[x].replace('.json', '')
        crons.push(c)
      }
    }
    return crons
  },
  exists: function (crons, cronID) {
    for (var c = 0; c < crons.length; c++) {
      if (crons[c].id === cronID) {
        return true
      }
    }
    return false
  },
  equalCrons: function (cronA, cronB) {
    if (
      cronA.tab === cronB.tab &&
      cronA.url === cronB.url &&
      cronA.command === cronB.command &&
      cronA.type === cronB.type &&
      cronA.comment === cronB.comment &&
      cronA.filename === cronB.filename &&
      cronA.length === cronB.length &&
      cronA.user_id === cronB.user_id
      ) {
      return true
    } else {
      return false
    }
  },
  updateCron: function (database, cron, callback) {
    if (!goodCron(cron)) {
      return callback({
        status: 418
      })
    }
    if (!hasID(cron)) {
      return callback({
        status: 400
      })
    }
    var jsonfile = require('jsonfile')
    var id = cron.id
    delete cron.id
    var file = database + '/crons/' + id + '.json'
    jsonfile.writeFile(file, cron, function (err) {
      if (err) {
        callback({
          status: 500
        })
      } else {
        cron.id = id
        callback(null, cron)
      }
    })
  },
  deleteCron: function (database, id, callback) {
    if (typeof id === 'undefined') {
      return callback({
        status: 400
      })
    }
    var fs = require('fs')
    var file = database + '/crons/' + id + '.json'
    fs.unlink(file, function (err) {
      if (err) {
        callback({
          status: 500
        })
      } else {
        callback(null, id)
      }
    })
  },
  createCron: function (database, cron, callback) {
    if (!goodCron(cron)) {
      return callback({
        status: 418
      })
    }
    var jsonfile = require('jsonfile')
    var shortid = require('shortid')
    var id = shortid.generate()
    var file = database + '/crons/' + id + '.json'
    jsonfile.writeFile(file, cron, function (err) {
      if (err) {
        callback({
          status: 500
        })
      } else {
        cron.id = id

        callback(null, cron)
      }
    })
  }
}

function goodCron (cron) {
  if (typeof cron !== 'undefined' &&
typeof cron.tab !== 'undefined' &&
typeof cron.url !== 'undefined' &&
typeof cron.command !== 'undefined' &&
typeof cron.type !== 'undefined' &&
typeof cron.comment !== 'undefined' &&
typeof cron.filename !== 'undefined' &&
typeof cron.length !== 'undefined' &&
typeof cron.times_run !== 'undefined' &&
typeof cron.user_id !== 'undefined'
	) {
    return true
  } else {
    return false
  }
}

function hasID (cron) {
  if (typeof cron.id !== 'undefined') {
    return true
  } else {
    return false
  }
}
