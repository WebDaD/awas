/**
 * DATA Routes for Records
 */
module.exports = {
    load: function(database) {
        var records = []
        var fs = require('fs')
        var jsonfile = require('jsonfile')
        var files = fs.readdirSync(database + '/records')
        for (var x = 0; x < files.length; x++) {
            var f = database + '/records/' + files[x]
            var stats = fs.statSync(f)
            if (stats.size > 0) {
                var r = jsonfile.readFileSync(f)
                r.id = files[x].replace('.json', '')
                records.push(r)
            }
        }
        return records
    },
    updateRecord: function(database, record, callback = () => {}) {
        if (!goodRecord(record)) {
            return callback({ status: 418 });
        }
        if (!hasID(record)) {
            return callback({ status: 400 });
        }
        var jsonfile = require('jsonfile');
        var id = record.id;
        delete record.id;
        var file = database + '/records/' + id + '.json';

        jsonfile.writeFile(file, record, function(err) {
            if (err) {
                return callback({ status: 500 });
            }
            record.id = id;
            return callback(null, record);
        });
    },
    deleteRecord: function(database, id, callback) {
        if (typeof id === 'undefined') {
            return callback({
                status: 400
            })
        }
        var fs = require('fs')
        var file = database + '/records/' + id + '.json'
        fs.unlink(file, function(err) {
            if (err) {
                callback({
                    status: 500
                })
            } else {
                callback(null, id)
            }
        })
    },
    stopRecord: function(database, id, callback) {
        if (typeof id === 'undefined') {
            return callback({
                status: 400
            })
        }
        var jsonfile = require('jsonfile')
        var fs = require('fs')
        var moment = require('moment')
        var ps = require('ps-node')
        var file = database + '/records/' + id + '.json'
        var r = jsonfile.readFileSync(file)
        r.stop = moment().tz('Europe/Berlin').format()
        r.id = id
        if (typeof r.pid !== 'undefined') {
            ps.kill(r.pid, function(err, stdout) {
                if (err) {
                    callback({
                        status: 500
                    })
                } else {
                    ps.kill(r.pid + 1, function(err, stdout) {
                        if (err) {
                            callback({
                                status: 500
                            })
                        } else {
                            module.exports.updateRecord(database, r, callback)
                        }
                    })
                }
            })
        } else {
            module.exports.updateRecord(database, r, callback)
        }
    },
    createRecord: function(database, record, callback) {
        if (!goodRecord(record)) {
            return callback({
                status: 418
            })
        }
        var jsonfile = require('jsonfile')
        var shortid = require('shortid')
        var id = shortid.generate()
        var file = database + '/records/' + id + '.json'
        jsonfile.writeFile(file, record, function(err) {
            if (err) {
                callback({
                    status: 500
                })
            } else {
                record.id = id

                callback(null, record)
            }
        })
    }
}

function goodRecord(record) {
    if (typeof record !== 'undefined' &&
        typeof record.url !== 'undefined' &&
        typeof record.start !== 'undefined' &&
        typeof record.stop !== 'undefined' &&
        typeof record.comment !== 'undefined' &&
        typeof record.filename !== 'undefined' &&
        typeof record.command !== 'undefined' &&
        typeof record.type !== 'undefined' &&
        typeof record.user_id !== 'undefined'
    ) {
        return true
    } else {
        return false
    }
}

function hasID(record) {
    if (typeof record.id !== 'undefined') {
        return true
    } else {
        return false
    }
}