frappe.ui.form.on("Indeed Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "indeed.api.test_connection",
				freeze: true,
				freeze_message: __("Contacting Indeed..."),
				callback: (r) => {
					if (r.message && r.message.ok) {
						frappe.show_alert({
							message: __("Connected to Indeed"),
							indicator: "green",
						});
					}
				},
			});
		});

		frm.add_custom_button(__("Sync Applications Now"), () => {
			frappe.call({
				method: "indeed.api.sync_applications_now",
				freeze: true,
				callback: () =>
					frappe.show_alert({
						message: __("Application sync complete"),
						indicator: "blue",
					}),
			});
		});
	},
});
