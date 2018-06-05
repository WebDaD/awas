var jsonfile = require('jsonfile')
var shortid = require('shortid')
var md5 = require('MD5')
var readlineSync = require('readline-sync')
var config = require('./config.json')

console.log('Welcome to the User Creator for AWAS!')

var user = {}
user.name = readlineSync.question('Enter Name: ')
user.login = readlineSync.question('Enter Login: ')
user.email = readlineSync.question('Enter E-Mail: ')
user.password = readlineSync.question('Enter Password: ', {
  hideEchoBack: true
})
user.passwordRepeat = readlineSync.question('Repeat Password: ', {
  hideEchoBack: true
})
while (user.password !== user.passwordRepeat) {
  console.error('Passwords do not match, please try again (or STRG+C to exit)')
  user.passwordRepeat = readlineSync.question('Repeat Password: ', {
    hideEchoBack: true
  })
}
user.admin = 0
if (readlineSync.keyInYN('Is this an Admin-User? [yn] ')) {
  user.admin = 1
}
user.password = md5(user.password)
user.token = md5(user.id + user.login + user.password)
user.id = shortid.generate()
jsonfile.writeFile(config.database + '/users/' + user.id + '.json', user, function (err) {
  if (err) {
    console.error(err)
    process.exit(1)
  } else {
    console.log('User has been created, Restart Awas-Main to see effect!')
    process.exit(0)
  }
})
