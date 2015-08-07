//users
function user_new() {
	$("#dialog-user-error").hide();
	$("#dialog-user-name").val("");
	$("#dialog-user-login").val("");
	$("#dialog-user-email").val("");
	$("#dialog-user-password").val("");
	$('#dialog-user').modal('show');
}

function user_edit(id) {
	var user = $("#" + id).data("user");
	$("#dialog-user-error").hide();
	$("#dialog-user-name").val(user.name);
	$("#dialog-user-login").val(user.login);
	$("#dialog-user-email").val(user.email);
	$("#dialog-user-password").val(user.password);
	$("#dialog-user-id").val(id);
	dialog_user_admin(user.admin);
	$('#dialog-user').modal('show');
}

function user_delete(id) {
	$("#" + id).find(".btn").addClass("hidden");
	$("#" + id).find(".delete_decide").removeClass("hidden");
}

function user_delete_cancel(id) {
	$("#" + id).find(".hidden").removeClass("hidden");
	$("#" + id).find(".delete_decide").addClass("hidden");
}

function user_delete_confirm(id) {
	$.ajax({
		url: 'users/' + id,
		type: "DELETE",
		headers: {
			token: token
		},
		dataType: 'json',
		statusCode: {
			200: function(data) {
				$('#dialog-user').modal('hide');
				$("#" + id).remove();
				toast("Anwender gelöscht", "success");
			},
			400: function(data) {
				dialogError("user","Bad Request");
			},
			401: function(data) {
				dialogError("user","Not Logged In?");
			},
			500: function(data) {
				dialogError("user","Internal Server Error");
			}
		}
	});
}

function dialog_user_admin(isAdmin) {
	$("#dialog-user-admin").val(isAdmin);
	if (isAdmin) {
		$("#dialog-user-admin-yes").removeClass("btn-default").addClass("btn-primary");
		$("#dialog-user-admin-no").removeClass("btn-primary").addClass("btn-default");
	} else {
		$("#dialog-user-admin-no").removeClass("btn-default").addClass("btn-primary");
		$("#dialog-user-admin-yes").removeClass("btn-primary").addClass("btn-default");
	}
}

function dialog_user_save() {
	var user = {};
	var verb = "POST";
	var url = "/users/";
	// check if all data is there
	user.name = checkVal("user", "name", "Bitte Name eintragen!");
	user.login = checkVal("user", "login", "Bitte Login eintragen!");
	user.email = checkVal("user", "email", "Bitte E-Mail eintragen!");
	user.password = checkVal("user", "password", "Bitte Passwort eintragen!");
	user.admin = checkVal("user", "admin", "Bitte Admin auswählen!");

	if ($("#dialog-user-id").val().length !== 0) {
		verb = "PUT";
		url += $("#dialog-user-id").val();
	}

	if (checkObj(user)) {
		return;
	} else {
		user.password = $.md5(user.password);
		$.ajax({
			url: url,
			type: verb,
			data: JSON.stringify({user:user}),
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
					dialogError("user","Bad Request");
				},
				401: function(data) {
					dialogError("user","Not Logged In?");
				},
				418: function(data) {
					dialogError("user","Not a valid object sent");
				},
				500: function(data) {
					dialogError("user","Internal Server Error");
				}
			}
		});
	}

}
