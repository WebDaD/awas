$.fn.croneditor = function(opts) {

    var el = this;

    // Write the HTML template to the document
    $(el).html(tmpl);

    var cronArr = ["*", "*", "*", "*", "*"];
    if (typeof opts.value === "string") {
        cronArr = opts.value.split(' ');
    }

    $(".tabs").tabs({
        activate: function(event, ui) {
            switch ($(ui.newTab).attr('id')) {

                // Minutes
                case 'button-minute-every':
                    cronArr[0] = "*";
                    break;
                case 'button-minute-n':
                    cronArr[0] = "*/" + $("#tabs-minute .slider").slider("value");
                    break;
                case 'button-minute-each':
                    cronArr[0] = "*";
                    // TODO: toggle off selected minutes on load
                    //$('.tabs-minute-format input[checked="checked"]').click()
                    $('.tabs-minute-format').html('');
                    drawEachMinutes();
                    break;

                    // Hours
                case 'button-hour-every':
                    cronArr[1] = "*";
                    break;
                case 'button-hour-n':
                    cronArr[1] = "*/" + $("#tabs-hour .slider").slider("value");
                    break;
                case 'button-hour-each':
                    cronArr[1] = "*";
                    $('.tabs-hour-format').html('');
                    drawEachHours();
                    break;

                    // Days
                case 'button-day-every':
                    cronArr[2] = "*";
                    break;
                case 'button-day-each':
                    cronArr[2] = "*";
                    $('.tabs-day-format').html('');
                    drawEachDays();
                    break;

                    // Months
                case 'button-month-every':
                    cronArr[3] = "*";
                    break;
                case 'button-month-each':
                    cronArr[3] = "*";
                    $('.tabs-month-format').html('');
                    drawEachMonths();
                    break;

                    // Weeks
                case 'button-week-every':
                    cronArr[4] = "*";
                    break;
                case 'button-week-each':
                    cronArr[4] = "*";
                    $('.tabs-week-format').html('');
                    drawEachWeek();
                    break;

            }

            drawCron();
        }
    });

    function drawCron() {

        var newCron = cronArr.join(' ');
        $('#cronString').val(newCron);

    }

    $('#clear').click(function() {
        $('#cronString').val('* * * * *');
        cronArr = ["*", "*", "*", "*", "*"];

    });

    $("#tabs-minute .slider").slider({
        min: 1,
        max: 59,
        slide: function(event, ui) {
            cronArr[0] = "*/" + ui.value;
            $('#tabs-minute-n .preview').html('Alle ' + ui.value + ' Minute(n)');
            drawCron();
        }
    });

    $("#tabs-hour .slider").slider({
        min: 1,
        max: 23,
        slide: function(event, ui) {
            cronArr[1] = "*/" + ui.value;
            $('#tabs-hour-n .preview').html('Alle ' + ui.value + ' Stunde(n)');
            drawCron();
        }
    });

    // TOOD: All draw* functions can be combined into a few smaller methods

    function drawEachMinutes() {
        // minutes
        for (var i = 0; i < 60; i++) {
            var padded = i;
            if (padded.toString().length === 1) {
                padded = "0" + padded;
            }
            $('.tabs-minute-format').append('<input type="checkbox" id="minute-check' + i + '"><label for="minute-check' + i + '">' + padded + '</label>');
            if (i !== 0 && (i + 1) % 10 === 0) {
                $('.tabs-minute-format').append('<br/>');
            }
        }
        $('.tabs-minute-format input').button();
        $('.tabs-minute-format').buttonset();

        $('.tabs-minute-format input[type="checkbox"]').click(function() {
            var newItem = $(this).attr('id').replace('minute-check', '');
            if (cronArr[0] === "*") {
                cronArr[0] = $(this).attr('id').replace('minute-check', '');
            } else {

                // if value already in list, toggle it off
                var list = cronArr[0].split(',');
                if (list.indexOf(newItem) !== -1) {
                    list.splice(list.indexOf(newItem), 1);
                    cronArr[0] = list.join(',');
                } else {
                    // else toggle it on
                    cronArr[0] = cronArr[0] + "," + newItem;
                }
                if (cronArr[0] === "") {
                    cronArr[0] = "*";
                }
            }
            drawCron();
        });

    }


    function drawEachHours() {
        // hours
        for (var i = 0; i < 24; i++) {
            var padded = i;
            if (padded.toString().length === 1) {
                padded = "0" + padded;
            }
            $('.tabs-hour-format').append('<input type="checkbox" id="hour-check' + i + '"><label for="hour-check' + i + '">' + padded + '</label>');
            if (i !== 0 && (i + 1) % 12 === 0) {
                $('.tabs-hour-format').append('<br/>');
            }
        }

        $('.tabs-hour-format input').button();
        $('.tabs-hour-format').buttonset();


        $('.tabs-hour-format input[type="checkbox"]').click(function() {
            var newItem = $(this).attr('id').replace('hour-check', '');
            if (cronArr[1] === "*") {
                cronArr[1] = $(this).attr('id').replace('hour-check', '');
            } else {

                // if value already in list, toggle it off
                var list = cronArr[1].split(',');
                if (list.indexOf(newItem) !== -1) {
                    list.splice(list.indexOf(newItem), 1);
                    cronArr[1] = list.join(',');
                } else {
                    // else toggle it on
                    cronArr[1] = cronArr[1] + "," + newItem;
                }
                if (cronArr[1] === "") {
                    cronArr[1] = "*";
                }
            }
            drawCron();
        });

    }

    function drawEachDays() {

        // days
        for (var i = 1; i < 32; i++) {
            var padded = i;
            if (padded.toString().length === 1) {
                padded = "0" + padded;
            }
            $('.tabs-day-format').append('<input type="checkbox" id="day-check' + i + '"><label for="day-check' + i + '">' + padded + '</label>');
            if (i !== 0 && (i) % 7 === 0) {
                $('.tabs-day-format').append('<br/>');
            }
        }

        $('.tabs-day-format input').button();
        $('.tabs-day-format').buttonset();

        $('.tabs-day-format input[type="checkbox"]').click(function() {
            var newItem = $(this).attr('id').replace('day-check', '');
            if (cronArr[2] === "*") {
                cronArr[2] = $(this).attr('id').replace('day-check', '');
            } else {

                // if value already in list, toggle it off
                var list = cronArr[2].split(',');
                if (list.indexOf(newItem) !== -1) {
                    list.splice(list.indexOf(newItem), 1);
                    cronArr[2] = list.join(',');
                } else {
                    // else toggle it on
                    cronArr[2] = cronArr[2] + "," + newItem;
                }
                if (cronArr[2] === "") {
                    cronArr[2] = "*";
                }

            }
            drawCron();
        });

    }


    function drawEachMonths() {
        // months
        var months = [null, 'Jan', 'Feb', 'März', 'April', 'Mai', 'Juni', 'Juli', 'Aug', 'Sept', 'Okt', 'Nov', 'Dez'];

        for (var i = 1; i < 13; i++) {
            var padded = i;
            if (padded.toString().length === 1) {
                //padded = "0" + padded;
            }
            $('.tabs-month-format').append('<input type="checkbox" id="month-check' + i + '"><label for="month-check' + i + '">' + months[i] + '</label>');
        }

        $('.tabs-month-format input').button();
        $('.tabs-month-format').buttonset();


        $('.tabs-month-format input[type="checkbox"]').click(function() {
            var newItem = $(this).attr('id').replace('month-check', '');
            if (cronArr[3] === "*") {
                cronArr[3] = $(this).attr('id').replace('month-check', '');
            } else {

                // if value already in list, toggle it off
                var list = cronArr[3].split(',');
                if (list.indexOf(newItem) !== -1) {
                    list.splice(list.indexOf(newItem), 1);
                    cronArr[3] = list.join(',');
                } else {
                    // else toggle it on
                    cronArr[3] = cronArr[3] + "," + newItem;
                }
                if (cronArr[3] === "") {
                    cronArr[3] = "*";
                }

            }
            drawCron();
        });

    }

    function drawEachWeek() {
        // weeks
        var days = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];
        for (var i = 0; i < 7; i++) {
            var padded = i;
            if (padded.toString().length === 1) {
                //padded = "0" + padded;
            }

            $('.tabs-week-format').append('<input type="checkbox" id="week-check' + i + '"><label for="week-check' + i + '">' + days[i] + '</label>');
        }

        $('.tabs-week-format input').button();
        $('.tabs-week-format').buttonset();

        $('.tabs-week-format input[type="checkbox"]').click(function() {
            var newItem = $(this).attr('id').replace('week-check', '');
            if (cronArr[4] === "*") {
                cronArr[4] = $(this).attr('id').replace('week-check', '');
            } else {

                // if value already in list, toggle it off
                var list = cronArr[4].split(',');
                if (list.indexOf(newItem) !== -1) {
                    list.splice(list.indexOf(newItem), 1);
                    cronArr[4] = list.join(',');
                } else {
                    // else toggle it on
                    cronArr[4] = cronArr[4] + "," + newItem;
                }
                if (cronArr[4] === "") {
                    cronArr[4] = "*";
                }

            }
            drawCron();
        });

    }

    // TODO: Refactor these methods into smaller methods
    drawEachMinutes();
    drawEachHours();
    drawEachDays();
    drawEachMonths();
    drawCron();
};

// HTML Template for plugin
var tmpl = '<input type="text" id="cronString" value="* * * * *" size="80" style="width:100%;"/>\
<br/>\
<div id="tabs" class="tabs">\
  <ul>\
    <li><a href="#tabs-minute">Minute</a></li>\
    <li><a href="#tabs-hour">Stunde</a></li>\
    <li><a href="#tabs-day">Tag im Monat</a></li>\
    <li><a href="#tabs-month">Monat</a></li>\
    <li><a href="#tabs-week">Tag der Woche</a></li>\
  </ul>\
  <div id="tabs-minute">\
    <div class="tabs">\
      <ul>\
        <li id="button-minute-every"><a href="#tabs-minute-every">Jede Minute</a></li>\
        <li id="button-minute-n"><a href="#tabs-minute-n">Alle n Minuten</a></li>\
        <li id="button-minute-each"><a href="#tabs-minute-each">Jede ausgewählte Minute</a></li>\
      </ul>\
      <div id="tabs-minute-every" class="preview">\
        <div>*</div>\
        <divJede Minute.</div>\
      </div>\
      <div id="tabs-minute-n">\
        <div class="preview"> Alle 1 Minute(n)</div>\
        <div class="slider"></div>\
      </div>\
      <div id="tabs-minute-each" class="preview">\
        <div>Jede ausgewählte Minute</div><br/>\
        <div class="tabs-minute-format"></div>\
      </div>\
    </div>\
  </div>\
  <div id="tabs-hour">\
    <div class="tabs">\
      <ul>\
        <li id="button-hour-every"><a href="#tabs-hour-every">Jede Stunde</a></li>\
        <li id="button-hour-n"><a href="#tabs-hour-n">Alle n Stunden</a></li>\
        <li id="button-hour-each"><a href="#tabs-hour-each">Jede ausgewählte Stunde</a></li>\
      </ul>\
      <div id="tabs-hour-every" class="preview">\
        <div>*</div>\
        <div>Jede Stunde</div>\
      </div>\
      <div id="tabs-hour-n">\
        <div class="preview">Alle 1 Stunde(n)</div>\
        <div class="slider"></div>\
      </div>\
      <div id="tabs-hour-each" class="preview">\
        <div>Jede ausgewählte Stunde</div><br/>\
        <div class="tabs-hour-format"></div>\
      </div>\
    </div>\
  </div>\
  <div id="tabs-day">\
    <div class="tabs">\
      <ul>\
        <li id="button-day-every"><a href="#tabs-day-every">Jeden Tag</a></li>\
        <li id="button-day-each"><a href="#tabs-day-each">Jeden ausgewählten Tag</a></li>\
      </ul>\
      <div id="tabs-day-every" class="preview">\
        <div>*</div>\
        <div>Jeden Tag</div>\
      </div>\
      <div id="tabs-day-each" class="preview">\
        <div>Jeden ausgewählten Tag</div><br/>\
        <div class="tabs-day-format"></div>\
      </div>\
    </div>\
  </div>\
  <div id="tabs-month">\
    <div class="tabs">\
      <ul>\
        <li id="button-month-every"><a href="#tabs-month-every">Jeden Monat</a></li>\
        <li id="button-month-each"><a href="#tabs-month-each">Jeden ausgewählten Monat</a></li>\
      </ul>\
      <div id="tabs-month-every" class="preview">\
        <div>*</div>\
        <div>Jeden Monat</div>\
      </div>\
      <div id="tabs-month-each" class="preview">\
        <div>Jeden ausgewählten Monat</div><br/>\
        <div class="tabs-month-format"></div>\
      </div>\
    </div>\
  </div>\
  <div id="tabs-week">\
    <div class="tabs">\
      <ul>\
        <li id="button-week-every"><a href="#tabs-week-every">Jeden Tag in der Woche</a></li>\
        <li id="button-week-each"><a href="#tabs-week-each">Jeden ausgewählten Tag in der Woche</a></li>\
      </ul>\
      <div id="tabs-week-every" class="preview">\
        <div>*</div>\
        <div>Jeden Tag in der Woche</div>\
      </div>\
      <div id="tabs-week-each">\
        <div class="preview">Jeden ausgewählten Tag in der Woche</div><br/>\
        <div class="tabs-week-format"></div>\
      </div>\
    </div>\
  </div>\
</div>';