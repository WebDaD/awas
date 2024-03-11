if ! type "json" > /dev/null; then
  echo '==> json not installed, installing'
  npm install -g json
fi
echo '=> Preparation Done.'

echo '=> Creating Database'
DOWNLOADS=$(json -f config.json downloads | sed -e 's/\n//g')
DATABASE=$(json -f config.json database | sed -e 's/\n//g' )

echo -n '==> Creating Folder Downloads...'
mkdir -p $DOWNLOADS
chmod 777 -R $DOWNLOADS
echo 'OK'

echo -n '==> Creating Folder Database + Subfolders...'
mkdir -p $DATABASE
chmod 777 -R $DATABASE
mkdir -p ${DATABASE}users
mkdir -p ${DATABASE}records
mkdir -p ${DATABASE}crons
mkdir -p ${DATABASE}archive
echo 'OK'

echo "Installing Ripper Software"
apt-get install streamripper vlc mplayer

echo "Installing pm2"
npm install -g pm2
