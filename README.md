# AWAS

Save and manage Audio-Streams on the web

## Installation

1. Install node.js: https://nodejs.org/en/download
2. Clone the Repository: `git clone https://github.com/WebDaD/awas.git`
3. Install Dependencies: `npm install`

## Start

`pm2 start app.js --name awas-demo -- 80800 `

## Dev-Start:

`pm2 start app.js --watch --ignore-watch="database public/css" --name awas-demo -- 80800 `
