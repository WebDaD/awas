/* global $ */
$(document).ready(function () {
  $('#dialog-record-start').datetimepicker({
    locale: 'de'
  })
  $('#dialog-record-stop').datetimepicker({
    locale: 'de'
  })
  $('[data-toggle=tooltip]').tooltip()

  $('#records .rstart').each(function () {
    var time = $(this).text()
    $(this).text(moment(time).format('DD.MM.YYYY HH:mm'))
  })
  $('#records .rstop').each(function () {
    var time = $(this).text()
    $(this).text(moment(time).format('DD.MM.YYYY HH:mm'))
  })
  $('#records .rspid').each(function () {
    if ($(this).text().length == 0) {
      $(this).parent().find('.rstopbutton').hide()
    } else {
      $(this).parent().find('.rstopbutton').show()
    }
  })
})

// records
function record_new () {
  $('#dialog-record-error').hide()
  $('#dialog-record-url').val('')
  $('#dialog-record-start').val('')
  $('#dialog-record-stop').val('')
  $('#dialog-record-comment').val('')
  $('#dialog-record-filename').val('')
  $('#dialog-record-type').val('mp3')
  $('#dialog-record-command').val('streamripper')
  $('#dialog-record').modal('show')
}

function record_edit (id) {
  var record = $('#' + id).data('record')
  $('#dialog-record-error').hide()
  $('#dialog-record-url').val(record.url)
  $('#dialog-record-start').val(moment(record.start).format('DD.MM.YYYY HH:mm'))
  $('#dialog-record-stop').val(moment(record.stop).format('DD.MM.YYYY HH:mm'))
  $('#dialog-record-comment').val(record.comment)
  $('#dialog-record-filename').val(record.filename)
  $('#dialog-record-type').val(record.type)
  $('#dialog-record-command').val(record.command)
  $('#dialog-record-id').val(id)
  $('#dialog-record').modal('show')
}

function record_delete (id) {
  $('#' + id).find('.btn').addClass('hidden')
  $('#' + id).find('.delete_decide').removeClass('hidden')
}

function record_delete_cancel (id) {
  $('#' + id).find('.hidden').removeClass('hidden')
  $('#' + id).find('.delete_decide').addClass('hidden')
}

function record_delete_confirm (id) {
  $.ajax({
    url: 'records/' + id,
    type: 'DELETE',
    headers: {
      token: token
    },
    dataType: 'json',
    statusCode: {
      200: function (data) {
        $('#dialog-record').modal('hide')
        $('#' + id).remove()
        toast('Aufnahme gelöscht', 'success')
      },
      400: function (data) {
        dialogError('record', 'Bad Request')
      },
      401: function (data) {
        dialogError('record', 'Not Logged In?')
      },
      500: function (data) {
        dialogError('record', 'Internal Server Error')
      }
    }
  })
}
function record_stop (id) {
  $.ajax({
    url: 'records/' + id + '/stop',
    type: 'POST',
    headers: {
      token: token
    },
    dataType: 'json',
    statusCode: {
      200: function (data) {
        toast('Aufnahme gestoppt', 'success')
        location.reload(true)
      },
      400: function (data) {
        dialogError('record', 'Bad Request')
      },
      401: function (data) {
        dialogError('record', 'Not Logged In?')
      },
      500: function (data) {
        dialogError('record', 'Internal Server Error')
      }
    }
  })
}
function dialog_record_save () {
  var record = {}
  var verb = 'POST'
  var url = '/records/'
	// check if all data is there
  record.url = checkVal('record', 'url', 'Bitte URL eintragen!')
  record.start = checkVal('record', 'start', 'Bitte Startzeit eintragen!')
  record.stop = checkVal('record', 'stop', 'Bitte Endzeit eintragen!')
  record.filename = checkVal('record', 'filename', 'Bitte Dateiname eintragen!')
  record.command = checkVal('record', 'command', 'Bitte Kommando auswählen!')
  record.type = checkVal('record', 'type', 'Bitte Dateityp auswählen!')
	// remove spaces in filename
  record.filename = record.filename.split(' ').join('_')
  record.comment = $('#dialog-record-comment').val()
  record.user_id = user
  if ($('#dialog-record-id').val().length !== 0) {
    verb = 'PUT'
    url += $('#dialog-record-id').val()
  }

  if (checkObj(record)) {

  } else {
    record.start = moment(record.start, 'DD.MM.YYYY HH:mm').format()
    record.stop = moment(record.stop, 'DD.MM.YYYY HH:mm').format()
    $.ajax({
      url: url,
      type: verb,
      data: JSON.stringify({record: record}),
      headers: {
        token: token
      },
      contentType: 'application/json; charset=utf-8',
      dataType: 'json',
      statusCode: {
        200: function (data) {
          location.reload(true)
        },
        201: function (data) {
          location.reload(true)
        },
        400: function (data) {
          dialogError('record', 'Bad Request')
        },
        401: function (data) {
          dialogError('record', 'Not Logged In?')
        },
        418: function (data) {
          dialogError('record', 'Not a valid object sent')
        },
        500: function (data) {
          dialogError('record', 'Internal Server Error')
        }
      }
    })
  }
}
function archive_delete (id) {
  $('#' + id).find('.btn').addClass('hidden')
  $('#' + id).find('.delete_decide').removeClass('hidden')
}

function archive_delete_cancel (id) {
  $('#' + id).find('.hidden').removeClass('hidden')
  $('#' + id).find('.delete_decide').addClass('hidden')
}

function archive_delete_confirm (id) {
  $.ajax({
    url: 'archive/' + id,
    type: 'DELETE',
    headers: {
      token: token
    },
    dataType: 'json',
    statusCode: {
      200: function (data) {
        $('#dialog-record').modal('hide')
        $('#' + id).remove()
        toast('Aufnahme gelöscht', 'success')
      },
      400: function (data) {
        dialogError('record', 'Bad Request')
      },
      401: function (data) {
        dialogError('record', 'Not Logged In?')
      },
      500: function (data) {
        dialogError('record', 'Internal Server Error')
      }
    }
  })
}
