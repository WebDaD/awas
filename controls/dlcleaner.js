var fs = require('fs')
var path = require('path')
var CronJob3 = require('cron').CronJob
var conf = require('../config.json')

var job = new CronJob3('00 * * * * *', function () {
  console.log('DLC TICK')
  fs.readdir(conf.downloads, function (err, files) {
    if (err) throw err
    files.forEach(function (file) {
      var ext = path.extname(file)
      if (ext === '.cue') {
        console.log('Deleting ' + file)
        fs.unlinkSync(path.join(conf.downloads, file))
      }
    })
  })
}, null, true, 'Europe/Berlin')

console.log("Cronjob 'DL-Cleaner' running: " + job.running)
