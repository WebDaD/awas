/**
 * Web Routes for Records
 */
module.exports = function(app, data, functions) {

    app.get('/files.html', functions.isLoggedIn(data.loggedIn), functions.isAdmin(data.admins), function(req, res) {
        readInFiles(app.downloads, function(err, files) {
            if (err) {
                data.files = [err];
            } else {
                data.files = [];
                var fs = require('fs');
                var filesize = require('filesize');
                var shortid = require('shortid');

                var moment = require('moment');
                for (var x = 0; x < files.length; x++) {
                    var f = {};
                    var fst = fs.statSync(app.downloads + '/' + files[x]);
                    f.name = files[x];
                    f.size = filesize.filesize(fst.size);
                    f.id = shortid.generate();
                    f.created = moment(fst.ctime).format("DD.MM.YYYY HH:mm:ss");
                    if (f.name.indexOf("_id-") > -1) {
                        var id = f.name.split("_id-")[1].split(".")[0];
                        f.name_nice = f.name.split("_id-")[0] + "." + f.name.split("_id-")[1].split(".")[1];
                        var rname = data.records.findObject(id, "id");
                        if (rname === "") {
                            var aname = data.archive.findObject(id, "id");
                            if (aname === "") {
                                var cname = data.crons.findObject(id, "id");
                                if (cname === "") {
                                    f.user = "NUF";
                                } else {
                                    f.user = cname.user_id;
                                }
                            } else {
                                f.user = aname.user_id;
                            }
                        } else {
                            f.user = rname.user_id;
                        }
                    } else {
                        f.name_nice = f.name;
                        f.user = "?";
                    }
                    data.files.push(f);
                }
            }
            data.admin = req.admin;
            data.ftp_port = app.ftp_port;
            res.render("files", data);
        });
    });
    app.use((req, res, next) => {
        try {
            // Encode it again to ensure proper encoding
            req.url = encodeURI(req.url);
            next();
        } catch (err) {
            console.error('Invalid URL:', req.url, err);
            res.status(400).send('Bad Request: Invalid URL encoding');
        }
    });
    app.get('/files/:file', functions.isLoggedIn(data.loggedIn), function(req, res) {
        if (!req.params.file) {
            return res.sendStatus(404);
        }

        var path = require('path');
        var mime = require('mime-types');
        var fs = require('fs');

        var file = app.downloads + '/' + decodeURIComponent(req.params.file);
        var nicefilename = path.basename(file);

        if (req.params.file.includes("_id-")) {
            let parts = req.params.file.split("_id-");
            nicefilename = `${parts[0]}.${parts[1].split(".")[1]}`;
        }

        var mimetype = mime.lookup(file) || 'application/octet-stream';

        res.setHeader('Content-Disposition', `attachment; filename="${nicefilename}"`);
        res.setHeader('Content-Type', mimetype);

        fs.access(file, fs.constants.F_OK, (err) => {
            if (err) {
                return res.status(404).send("File not found.");
            }
            var filestream = fs.createReadStream(file);
            filestream.pipe(res);
        });
    });

    app.delete('/files/:file', functions.isLoggedIn(data.loggedIn), function(req, res) {
        if (!req.params.file) {
            return res.sendStatus(400);
        }

        var fs = require('fs');
        var file = app.downloads + "/" + decodeURIComponent(req.params.file);

        fs.unlink(file, function(err) {
            if (err) {
                console.error("Error deleting file:", err);
                return res.status(500).send("File deletion failed.");
            }
            res.sendStatus(200);
        });
    });
};

function readInFiles(path, callback) {
    var fs = require('fs');
    fs.readdir(path, function(err, files) {
        callback(err, files);
    });
}
Array.prototype.findObject = function(searchFor, property) {
    var retVal = -1;
    var self = this;
    for (var index = 0; index < self.length; index++) {
        var item = self[index];
        if (item.hasOwnProperty(property)) {
            if (item[property].toLowerCase() === searchFor.toLowerCase()) {
                retVal = index;
                return this[retVal];
            }
        }
    }
    return "";
};