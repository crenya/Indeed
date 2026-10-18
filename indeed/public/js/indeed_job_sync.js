frappe.ui.form.on("Indeed Job Sync", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (["Failed", "Queued", "Pending"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Retry Now"), () => {
				frappe.call({
					method: "indeed.api.retry_now",
					args: { job_sync: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}
	},
});
