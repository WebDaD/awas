# AWAS 3

AWAS 3 is a from-scratch rewrite of the AWAS stream recorder. The `v3` branch is
independent of the legacy Node.js application on `master`.

Version 3.0.2 provides the production foundation, authentication, stream
management and recording:

- Python 3.12 or newer, FastAPI and Jinja2
- SQLAlchemy 2 and Alembic
- SQLite in WAL mode
- planning as the factual start page, with all running recordings plus upcoming and
  recurring entries
- a separate schedule history page
- mobile-only collapsible main navigation
- JSON health endpoint
- native systemd service and nginx reverse proxy with parallel HTTP and optional HTTPS
- installer for 64-bit Raspberry Pi OS/Debian and Ubuntu
- administrator and user roles without public registration
- users can add and edit all streams, create schedules, and manage their own
  schedules, history entries and recordings; administrators can manage every entry
- Argon2id password hashing and server-side, revocable sessions
- separate HTTP and HTTPS session cookies so HTTPS tokens are never sent over HTTP
- CSRF protection, login throttling and security audit events
- responsive login, account and user-management pages
- administrator-only anonymized user deletion that retains planning, recording and
  history attribution as `Gelöschter Benutzer`, while protecting the current account
  and the last active administrator
- stream management with direct HTTP/HTTPS URLs
- server-side connection checks and an instant stream filter
- every stored stream is available for recording; stream management has no separate
  activation state
- one-click recordings from the stream list
- any number of spontaneous and planned recordings of the same stream can run in parallel
- a preferred recorder and file type per stream, with overrides that apply only to
  the individual schedule
- editable file-name bases for one-time and recurring schedules
- file-name bases retain underscores in addition to letters, numbers and hyphens
- administrator-managed argument templates for every recorder
- streamripper, ffmpeg, streamlink, vlc, mpv and mplayer recorder profiles
- recording history, stop control and authenticated snapshot downloads while recording
- running planned and spontaneous recordings expose the same file name, live file size,
  download and permitted stop controls on the planning and recordings pages
- one-time recording schedules with local-time input
- discarded schedules disappear immediately and are not retained in the visible
  schedule history
- automatic start and stop with restart-aware continuation
- recurring schedules with configurable hourly, daily, weekly and monthly
  intervals, including fixed monthly dates and positions such as the first Monday
- pausable series with optional validity ranges and DST-safe occurrence generation
- future recurring occurrences represented only by their recurrence rule until they run
- automatic continuation of every time-limited recording after restarts and recorder
  failures, with retry delays of 15, 30, 60, 120 and at most 300 seconds
- manual termination of retrying schedules after an unexpected recorder exit
- planning section headings with the total number of listed entries
- recording storage overview with free-space and usage information
- administrator-configurable recording directory with a write-access check
- owner-or-administrator deletion of a recording entry and its associated file
- inline two-click confirmation for deleting, stopping and discarding with a
  five-second deadline; the blinking button reserves its full width and uses no popup
  or separate page
- stream deletion that retains recordings and detached recording history
- optional age-based automatic retention, disabled by default
- retention that deletes files while preserving recording history
- cleanup preview, inline two-click confirmation and a 100-file limit per run
- administrator export and validated replacement import of the complete SQLite database,
  including the persisted schedule history
- five-second live updates for running recordings, planning and storage data
- case-insensitive stream sorting with numeric and special-character prefixes first
- automatic removal of streamripper cue files when a recording ends
- consistent attribution of planning and recording entries to their initiating users
- stream URLs and recording files grouped visually with their respective entries
- desktop content using 90 percent of the available page width
- pale-orange highlighting for every row that represents a running recording
- interface with the digiandi logo, violet navigation, pale-violet page background
  and orange `#f87f40` action accents

## Supported base systems

- Raspberry Pi OS 64-bit based on Debian 13 (Pi 4 and newer)
- Debian 13 on `arm64` or `amd64`
- Ubuntu Server 24.04 LTS and 26.04 LTS on `arm64` or `amd64`

The application contains no Raspberry-Pi-specific code.

## Recorders

Each stream stores one preferred recorder and file type. Spontaneous
recordings use both immediately. One-time and recurring schedules preselect both
values and allow an override before the schedule is saved. Supported file types
are `ts`, `mp3`, `mp4`, `ogg`, `wma`, `wmv`, `mpg` and `flac`. The installer
provides these profiles:

| Selection | Program | Intended input |
|---|---|---|
| `streamripper` | streamripper | Shoutcast/Icecast-style radio streams |
| `ffmpeg` | ffmpeg | best video and audio stream, or best audio stream for audio-only input, copied without re-encoding |
| `ffmpeg-all` | ffmpeg | every input stream and every available quality, copied without re-encoding |
| `streamlink-http` | streamlink | progressive HTTP/HTTPS streams |
| `streamlink-hls-dash` | streamlink | HLS or DASH manifests |
| `vlc` | vlc | media inputs supported by vlc |
| `mpv` | mpv | media inputs supported by mpv |
| `mplayer` | mplayer | media inputs supported by mplayer |

`streamripper` accepts only `http://` stream addresses. AWAS rejects an
`https://` address when that recorder is selected and displays the reason directly
in the stream or planning form.

Administrators can inspect and edit every recorder's argument template under
**Rekorder**. Program paths remain fixed; parameters are split into a direct
argument list and are never executed through a shell. Templates use `{url}` and
`{output}`; `streamripper` uses `{output_base}` instead of `{output}` because it
adds the actual stream suffix itself. AWAS validates the required placeholders
before saving.

While a recording is running, its download link returns a fixed-size snapshot
of the bytes written when the request starts. Container formats that write their
index at the end may not be playable until the recording has been finalized.

Every planned recording is retried until its configured end time after an
unexpected recorder exit, regardless of the recorder's return code. Consecutive
short failures use delays of 15, 30, 60, 120 and then 300 seconds. A recording
attempt that runs for at least one minute resets the delay to 15 seconds. Each
successful restart creates a separate recording segment; spontaneous recordings
have no end time and are therefore not restarted automatically. A retrying schedule
can be stopped manually to prevent any further attempts.

Recorder diagnostics inherit the AWAS service's standard error output and are
therefore available in the system journal without being buffered in AWAS memory.
After streamripper exits, AWAS removes the cue file created alongside the recording.
The ffmpeg profiles retry network and streamed-input failures, but do not treat a
regular end-of-file as a connection failure. This keeps finite HLS playlists and
Akamai HLS inputs compatible while retaining reconnect handling for network outages.

For planned recordings, AWAS derives the file-name base from the description.
The value can be edited before saving. Date, time, a uniqueness token and the
selected extension are appended automatically for every generated recording.
Letters, numbers, hyphens and underscores are retained; other separators are
normalized.

Completed, missed and failed schedules remain in the separate schedule history
until their entries are removed manually. A schedule discarded before it starts
is not shown in the history. The history is stored in the SQLite database and is
included in database exports and imports. Removing a schedule-history entry does
not remove an associated recording.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp deploy/awas.example.toml awas.toml
AWAS_CONFIG="$PWD/awas.toml" alembic upgrade head
AWAS_CONFIG="$PWD/awas.toml" awas-admin create-admin
AWAS_CONFIG="$PWD/awas.toml" awas
```

Open <http://127.0.0.1:8080>. The health endpoint is available at
<http://127.0.0.1:8080/health>.

Run the checks with:

```bash
ruff check .
pytest
```

## Raspberry Pi / server installation

Clone or download the `v3` branch on the target system and run:

```bash
sudo bash scripts/install.sh
```

The installer creates the non-login system user `awas-service` and uses these paths:

| Purpose | Path |
|---|---|
| application and virtual environment | `/opt/awas` |
| configuration | `/etc/awas/awas.toml` |
| SQLite database | `/var/lib/awas/awas.db` |
| logs | `/var/log/awas` / system journal |
| recordings | `/srv/awas/recordings` |

On upgrades, the installer preserves existing AWAS nginx site files so locally
configured host names and certificate integration are not overwritten.

The recording directory can be changed under **Speicher**. The directory must
already exist; AWAS does not change ownership or permissions. The system user
`awas-service` needs read, write and execute permissions on the recording
directory and execute permission on every parent directory. For a dedicated new
directory, for example:

```bash
sudo install -d -o awas-service -g awas-service -m 0750 /srv/awas/new-recordings
```

The changed directory is used only for newly started recordings. Existing and
currently running recordings remain linked to the directory in which they were
started.

The complete SQLite database can be downloaded and restored under **Speicher**.
The backup includes users, password hashes, streams, schedules, recording history
and application settings. It does not include recording files or
`/etc/awas/awas.toml`; those must be backed up separately. Imports accept only a
complete database from the same AWAS database revision, require the currently
signed-in active administrator to exist in the backup, and are blocked while a
recording is running. After a successful import all older web sessions are revoked
while the importing administrator remains signed in. Database backup files contain
sensitive data and should be stored with restricted access.

After installation, open `http://IP-ADDRESS-OF-THE-SERVER/`.

### Optional HTTPS

AWAS keeps HTTP on port 80 and can additionally serve HTTPS on port 443. It
does not select a domain or obtain a certificate. Install the certificate and
private key manually through SSH at these paths:

| Purpose | Path |
|---|---|
| certificate including intermediate certificates | `/etc/awas/tls/fullchain.pem` |
| private key | `/etc/awas/tls/privkey.pem` |

For example:

```bash
sudo install -d -o root -g root -m 0700 /etc/awas/tls
sudo install -o root -g root -m 0644 fullchain.pem /etc/awas/tls/fullchain.pem
sudo install -o root -g root -m 0600 privkey.pem /etc/awas/tls/privkey.pem
sudo bash /opt/awas/app/scripts/enable-https.sh
```

The files may instead be symbolic links to certificates managed elsewhere.
After replacing or renewing them, validate and reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

The HTTP and HTTPS logins deliberately use different cookies. The HTTPS cookie
is always `Secure` and is never sent over HTTP, so switching protocol can require
a separate login. HTTP remains unencrypted and should only be exposed where that
is intentional. AWAS does not redirect HTTP to HTTPS and does not enable HSTS.

Create the first administrator interactively:

```bash
sudo -u awas-service env AWAS_CONFIG=/etc/awas/awas.toml \
  /opt/awas/.venv/bin/awas-admin create-admin
```

The password prompt does not echo any characters. Usernames use lowercase
letters, numbers, `.`, `_` and `-`, start with a letter, and contain 3–32 characters.

## Upgrade

Update the checkout and run the idempotent installer again. Existing
configuration and database contents are preserved; pending migrations run
while AWAS is stopped. Running scheduled recordings are finalized as interrupted
segments and automatically continued after the service restart when their end
time has not yet been reached.

```bash
cd ~/awas
git pull --ff-only
sudo bash scripts/install.sh
```

Useful checks:

```bash
sudo systemctl status awas
sudo journalctl -u awas -n 100 --no-pager
curl http://127.0.0.1:8080/health
```

nginx continues to expose HTTP on port 80. If the manually installed certificate
and key are present during an installation or upgrade, the installer also enables
HTTPS on port 443. Otherwise it prepares the HTTPS configuration and leaves it
disabled until `scripts/enable-https.sh` is run.

## Configuration

AWAS reads `/etc/awas/awas.toml` by default. Set `AWAS_CONFIG` to use another
file. See [`deploy/awas.example.toml`](deploy/awas.example.toml) for all current
settings.
