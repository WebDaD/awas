var token = "";
var user = "";
$(document).ready(function() {
	if ($.cookie('awas_token') !== undefined) {
		user = $.cookie('awas_user');
		token = $.cookie('awas_token');
	}
});




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
