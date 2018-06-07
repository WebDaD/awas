var diskspace = require('diskspace')
var filesize = require('filesize')
var disk = process.argv[2]
console.log('Checking ' + disk)

diskspace.check(disk, function (err, total) {
  if (err) {
    console.error(err)
  } else {
    try {
      console.log(total)
      var percentFree = Math.round((100 * (total.free)) / (total.total))
      console.log(percentFree)
      console.log(filesize(total.free).toString() + ' / ' + percentFree.toString() + '%')
    } catch (err) {
      console.error(err)
    }
  }
})
