$(document).ready(function() {
	$("#navigation").hide();
	$("#btn_logout").hide();
	$("#space_text").hide();
	$("#dialog-login-login").focus();
});
//login
function login() {
	var info = {};
	// check if all data is there
	info.login = checkVal("login", "login", "Bitte Login eintragen!");
	info.password = checkVal("login", "password", "Bitte Passwort eintragen!");
	if (checkObj(info)) {
		return;
	} else {
		info.password = $.md5(info.password);
		$.ajax({
			url: '/login',
			type: 'POST',
			data: JSON.stringify({info:info}),
			contentType: 'application/json; charset=utf-8',
			dataType:'json',
			statusCode: {
				200: function(data) {
					$.cookie('awas_token', data.token, { expires: 7, path: '/' });
					$.cookie('awas_user', data.user, { expires: 7, path: '/' });
					window.location.replace("records.html");
				},
				400: function(data) {
					toast("Bad Request","error");
				},
				401: function(data) {
					toast("Login failed","error");
				},
				418: function(data) {
					toast("Not a valid object sent","error");
				},
				500: function(data) {
					toast("Internal Server Error","error");
				}
			}
		});
	}

}
