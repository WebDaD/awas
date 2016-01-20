var http = require("http");
var moment = require("moment-timezone");

var server = http.createServer(function(req, res) {


  var now = moment().tz("Europe/Berlin");
  var start = moment("2015-07-09T15:43:00+02:00").tz("Europe/Berlin");


  res.write("<p>The Server time is " + now.format() + "</p>");
  res.write("<p>The Start time is " + start.format() + "</p>");
  res.write("<p>Start OK? " + now.isSame(start,"minute") + "</p>")

  res.end();

}).listen(8085);
console.log("running");
