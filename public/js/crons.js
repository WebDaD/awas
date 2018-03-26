$(document).ready(function () {
  $('[data-toggle=tooltip]').tooltip()
})
// crons
function cron_new () {
  $('#dialog-cron-error').hide()
  $('#dialog-cron-tab').croneditor({
    value: '* * * * *'
  })
  $('#dialog-cron-url').val('')
  $('#dialog-cron-comment').val('')
  $('#dialog-cron-length').val('')
  $('#dialog-cron-filename').val('')
  $('#dialog-cron-type').val('mp3')
  $('#dialog-cron-command').val('streamripper')
  $('#dialog-cron-times_run').val('0')
  $('#dialog-cron').modal('show')
}

function cron_edit (id) {
  var cron = $('#' + id).data('cron')
  $('#dialog-cron-error').hide()
  $('#dialog-cron-tab').croneditor({
    value: cron.tab
  })
  $('#dialog-cron-url').val(cron.url)
  $('#dialog-cron-comment').val(cron.comment)
  $('#dialog-cron-length').val(cron.length)
  $('#dialog-cron-filename').val(cron.filename)
  $('#dialog-cron-type').val(cron.type)
  $('#dialog-cron-command').val(cron.command)
  $('#dialog-cron-id').val(id)
  $('#dialog-cron-times_run').val(cron.times_run)
  $('#dialog-cron').modal('show')
}

function cron_delete (id) {
  $('#' + id).find('.btn').addClass('hidden')
  $('#' + id).find('.delete_decide').removeClass('hidden')
}

function cron_delete_cancel (id) {
  $('#' + id).find('.hidden').removeClass('hidden')
  $('#' + id).find('.delete_decide').addClass('hidden')
}

function cron_delete_confirm (id) {
  $.ajax({
    url: 'crons/' + id,
    type: 'DELETE',
    headers: {
      token: token
    },
    dataType: 'json',
    statusCode: {
      200: function (data) {
        $('#dialog-cron').modal('hide')
        $('#' + id).remove()
        toast('Cronjob gelöscht', 'success')
      },
      400: function (data) {
        dialogError('cron', 'Bad Request')
      },
      401: function (data) {
        dialogError('cron', 'Not Logged In?')
      },
      500: function (data) {
        dialogError('cron', 'Internal Server Error')
      }
    }
  })
}
function dialog_cron_save () {
  var cron = {}
  var verb = 'POST'
  var url = '/crons/'
	// check if all data is there
  cron.tab = $('#cronString').val()
  cron.url = checkVal('cron', 'url', 'Bitte URL eintragen!')
  cron.filename = checkVal('cron', 'filename', 'Bitte Dateiname eintragen!')
	// remove spaces in filename
  cron.filename = cron.filename.split(' ').join('_')
  cron.type = $('#dialog-cron-type').val()
  cron.command = $('#dialog-cron-command').val()
  cron.tab = $('#cronString').val()
  cron.comment = $('#dialog-cron-comment').val()
  cron.length = checkVal('cron', 'length', 'Bitte Länge eintragen!')
  cron.user_id = user
  cron.times_run = $('#dialog-cron-times_run').val()
  if ($('#dialog-cron-id').val().length !== 0) {
    verb = 'PUT'
    url += $('#dialog-cron-id').val()
  }

  if (checkObj(cron)) {

  } else {
    $.ajax({
      url: url,
      type: verb,
      data: JSON.stringify({cron: cron}),
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
          dialogError('cron', 'Bad Request')
        },
        401: function (data) {
          dialogError('cron', 'Not Logged In?')
        },
        418: function (data) {
          dialogError('cron', 'Not a valid object sent')
        },
        500: function (data) {
          dialogError('cron', 'Internal Server Error')
        }
      }
    })
  }
}
