frappe.ui.form.on("Job Opening", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Publish to Indeed"), () => {
			frappe.call({
				method: "indeed.api.publish_now",
				args: { job_opening: frm.doc.name },
				freeze: true,
				freeze_message: __("Queueing Indeed sync..."),
				callback: () => frm.reload_doc(),
			});
		});

		if (frm.doc.indeed_job_id) {
			frm.add_custom_button(__("Expire on Indeed"), () => {
				frappe.confirm(__("Remove this posting from Indeed?"), () => {
					frappe.call({
						method: "indeed.api.publish_now",
						args: { job_opening: frm.doc.name, expire: 1 },
						freeze: true,
						callback: () => frm.reload_doc(),
					});
				});
			});
		}

		frappe.call({
			method: "indeed.api.sync_status",
			args: { job_opening: frm.doc.name },
			callback: (r) => {
				const status = r.message && r.message.status;
				if (!status) return;
				if (status === "Failed") {
					frm.dashboard.set_headline(
						__("Indeed sync failed: {0}", [r.message.last_error || ""])
					);
				} else {
					frm.dashboard.set_headline(__("Indeed: {0}", [status]));
				}
			},
		});
	},
});
