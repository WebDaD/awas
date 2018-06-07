var diskspace = require('diskspace')
var filesize = require('filesize')
var disk = process.argv[2]
console.log('Checking ' + disk)

diskspace.check(disk, function (err, total2, free2, status2) {
  if (err) {
    console.error(err)
  } else {
    try {
      console.log(total2)
      console.log(total2 + ' - ' + free2 + ' - ' + status2)
      var percentFree = Math.round((100 * (free2)) / (total2))
      console.log(percentFree)
      console.log(filesize(free2).toString() + ' / ' + percentFree.toString() + '%')
    } catch (err) {
      console.error(err)
    }
  }
})
