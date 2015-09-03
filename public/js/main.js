var token = "";
var user = "";
$(document).ready(function() {
	if ($.cookie('awas_token') !== undefined) {
		user = $.cookie('awas_user');
		token = $.cookie('awas_token');
	}
	addToHomescreen({
		skipFirstVisit: true,
		maxDisplayCount: 1
	});
	if($('#btn_logout').is(':visible')) {
		displayActive();
		setInterval(function() {
			displayActive();
		}, 10 * 1000);
		$("#space_text").show();
		displaySpace();
		setInterval(function() {
			displaySpace();
		}, 10 * 1000);
	}
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
//Logout
function logout() {
	$.ajax({
		url: '/logout',
		type: 'POST',
		contentType: 'application/json; charset=utf-8',
		dataType: 'json',
		headers: {
			token: token
		},
		statusCode: {
			200: function(data) {
				$.removeCookie('awas_token', {
					path: '/'
				});
				$.removeCookie('awas_user', {
					path: '/'
				});
				user = "";
				token = "";
				window.location.replace("login.html");
			},
			400: function(data) {
				toast("Bad Request", "error");
			},
			500: function(data) {
				toast("Internal Server Error", "error");
			}
		}
	});
}


//All
function checkObj(obj) {
	return Object.keys(obj)
		.every(function(key) {
			switch (key) {
				default: return obj[key] === null; // `== null` to include `undefined`
			}
		});
}

function checkVal(dialog, field, msg) {
	if ($("#dialog-" + dialog + "-" + field).val().length === 0) {
		addError(dialog, field);
		return dialogError(dialog, msg);
	} else {
		clearError(dialog, field);
		return $("#dialog-" + dialog + "-" + field).val();
	}
}

function dialogError(dialog, msg) {
	$("#dialog-" + dialog + "-error").text(msg).show();
	setTimeout(function() {
		$("#dialog-" + dialog + "-error").fadeOut('fast');
	}, 6000);
	return null;
}

function addError(dialog, name) {
	$("#dialog-" + dialog + "-" + name + "-group").addClass("has-error has-feedback");
	$("#dialog-" + dialog + "-" + name + "-group").find("div.form-group div.input-group").append('<span class="glyphicon glyphicon-warning-sign form-control-feedback"></span>');
}

function clearError(dialog, name) {
	$("#dialog-" + dialog + "-" + name + "-group").find("div.form-group").removeClass("has-error has-feedback");
	$("#dialog-" + dialog + "-" + name + "-group").find("div.form-group div.input-group span.glyphicon.form-control-feedback").remove();
}

function toast(msg, style) {
	style = typeof style !== 'undefined' ? style : "info";
	var id = "alert_" + new Date().getTime();
	$("#alerts").append('<div id="' + id + '" class="alert alert-' + style + ' fade in"><a href="#" class="close" data-dismiss="alert" aria-label="close">&times;</a> ' + msg + '</div>');
	$("#" + id).fadeIn('fast');
	setTimeout(function() {
		$("#" + id).fadeOut('fast');
	}, 6000);
}
