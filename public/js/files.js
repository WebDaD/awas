//files
function file_delete(id) {
	$("#" + id).find(".btn").addClass("hidden");
	$("#" + id).find(".delete_decide").removeClass("hidden");
}

function file_delete_cancel(id) {
	$("#" + id).find(".hidden").removeClass("hidden");
	$("#" + id).find(".delete_decide").addClass("hidden");
}

function file_delete_confirm(id) {
	$.ajax({
		url: 'files/' + id,
		type: "DELETE",
		headers: {
			token: token
		},
		dataType: 'json',
		statusCode: {
			200: function(data) {
				$("#" + id).remove();
				toast("Datei gelöscht", "success");
			},
			400: function(data) {
				toast("Bad Request", "error");
			},
			401: function(data) {
				toast("Not Logged In?", "error");
			},
			500: function(data) {
				toast("Internal Server Error", "error");
			}
		}
	});
}
