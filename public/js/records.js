$(document).ready(function() {
	$('#dialog-record-start').datetimepicker({
		locale: 'de'
	});
	$('#dialog-record-stop').datetimepicker({
		locale: 'de'
	});
	$("[data-toggle=tooltip]").tooltip();
	displayActive();
	setInterval(function() {
		displayActive();
	}, 60 * 1000);
	displaySpace();
	setInterval(function() {
		displaySpace();
	}, 60 * 1000);
});
function displayActive(){ //.success
	$("#active_records").load("/active_records");
	$('#records > tbody > tr').removeClass("success");
	$('#records > tbody  > tr').each(function() {
		var data = $(this).data("record");
		if(typeof data !== 'undefined' && isActive(data)){
			$(this).addClass("success");
		}
	});
}
function displaySpace(){
		$.get("/space.pfree", function(data){
			var cclass = "";
			var p = parseInt(data);
			$("#space_text").removeClass("label-danger");
			$("#space_text").removeClass("label-warning");
			$("#space_text").removeClass("label-success");
			if(p < 10){
				cclass = "label-danger";
			} else if(p < 25){
				cclass = "label-warning";
			} else {
				cclass = "label-success";
			}
			$("#space_text").text("Speicherplatz: "+data+" frei");
			$("#space_text").addClass(cclass);
		});

}
function isActive(record) {
	var now = moment();
  var ra = moment(record.start+" +02:00", "DD.MM.YYYY HH:mm Z");
	var rs = moment(record.stop+" +02:00", "DD.MM.YYYY HH:mm Z");

	if (now.isBetween(ra,rs)) {
		return true;
	} else {
		return false;
	}
}
//records
function record_new() {
	$("#dialog-record-error").hide();
	$("#dialog-record-url").val("");
	$("#dialog-record-start").val("");
	$("#dialog-record-stop").val("");
	$("#dialog-record-comment").val("");
	$("#dialog-record-filename").val("");
	$('#dialog-record').modal('show');
}

function record_edit(id) {
	var record = $("#" + id).data("record");
	$("#dialog-record-error").hide();
	$("#dialog-record-url").val(record.url);
	$("#dialog-record-start").val(record.start);
	$("#dialog-record-stop").val(record.stop);
	$("#dialog-record-comment").val(record.comment);
	$("#dialog-record-filename").val(record.filename);
	$("#dialog-record-id").val(id);
	$('#dialog-record').modal('show');
}

function record_delete(id) {
	$("#" + id).find(".btn").addClass("hidden");
	$("#" + id).find(".delete_decide").removeClass("hidden");
}

function record_delete_cancel(id) {
	$("#" + id).find(".hidden").removeClass("hidden");
	$("#" + id).find(".delete_decide").addClass("hidden");
}

function record_delete_confirm(id) {
	$.ajax({
		url: 'records/' + id,
		type: "DELETE",
		headers: {
			token: token
		},
		dataType: 'json',
		statusCode: {
			200: function(data) {
				$('#dialog-record').modal('hide');
				$("#" + id).remove();
				toast("Aufnahme gelöscht", "success");
			},
			400: function(data) {
				dialogError("record","Bad Request");
			},
			401: function(data) {
				dialogError("record","Not Logged In?");
			},
			500: function(data) {
				dialogError("record","Internal Server Error");
			}
		}
	});
}

function dialog_record_save() {
	var record = {};
	var verb = "POST";
	var url = "/records/";
	// check if all data is there
	record.url = checkVal("record", "url", "Bitte URL eintragen!");
	record.start = checkVal("record", "start", "Bitte Startzeit eintragen!");
	record.stop = checkVal("record", "stop", "Bitte Endzeit eintragen!");
	record.filename = checkVal("record", "filename", "Bitte Dateiname eintragen!");
	//remove spaces in filename
	record.filename = record.filename.split(' ').join('_');
	record.comment = $("#dialog-record-comment").val();
	record.user_id = user;
	if ($("#dialog-record-id").val().length !== 0) {
		verb = "PUT";
		url += $("#dialog-record-id").val();
	}

	if (checkObj(record)) {
		return;
	} else {
		$.ajax({
			url: url,
			type: verb,
			data: JSON.stringify({record:record}),
			headers: {
				token: token
			},
			contentType: 'application/json; charset=utf-8',
			dataType:'json',
			statusCode: {
				200: function(data) {
					location.reload(true);
				},
				201: function(data) {
					location.reload(true);
				},
				400: function(data) {
					dialogError("record","Bad Request");
				},
				401: function(data) {
					dialogError("record","Not Logged In?");
				},
				418: function(data) {
					dialogError("record","Not a valid object sent");
				},
				500: function(data) {
					dialogError("record","Internal Server Error");
				}
			}
		});
	}

}
function archive_delete(id) {
	$("#" + id).find(".btn").addClass("hidden");
	$("#" + id).find(".delete_decide").removeClass("hidden");
}

function archive_delete_cancel(id) {
	$("#" + id).find(".hidden").removeClass("hidden");
	$("#" + id).find(".delete_decide").addClass("hidden");
}

function archive_delete_confirm(id) {
	$.ajax({
		url: 'archive/' + id,
		type: "DELETE",
		headers: {
			token: token
		},
		dataType: 'json',
		statusCode: {
			200: function(data) {
				$('#dialog-record').modal('hide');
				$("#" + id).remove();
				toast("Aufnahme gelöscht", "success");
			},
			400: function(data) {
				dialogError("record","Bad Request");
			},
			401: function(data) {
				dialogError("record","Not Logged In?");
			},
			500: function(data) {
				dialogError("record","Internal Server Error");
			}
		}
	});
}
