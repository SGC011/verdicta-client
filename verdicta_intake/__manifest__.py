{
    "name": "Verdicta Client Intake",
    "summary": "Reusable, self-closing clarification form for Verdicta clients",
    "description": """
Reusable client intake / clarification form.

* Questions are data, not code. Add, edit, reorder, retire or un-retire them
  from the Odoo backend at any time - no deploy required.
* A question is removed from the public form automatically once the client
  answers it (``auto_close``), so the form only ever shows outstanding items.
* Every submission is stored, snapshotted, and rendered to an A4 PDF which can
  be regenerated at any time.
* Each client gets a private access code. The public form cannot be reached
  without one.
* Submissions and questions are readable only by members of the
  "Verdicta Intake" group. The public user and ordinary accounting users have
  no access to client answers at all.
""",
    "author": "SGC TECH AI",
    "website": "https://sgctech.ai",
    "category": "Accounting",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
"depends": [
        "base",
        "web",
        "mail",
        "portal",
        "website",
        "account",
    ],
    "data": [
        "security/verdicta_intake_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "data/mail_template_data.xml",
        "data/mail_template_nudge.xml",
        "report/verdicta_intake_report.xml",
        "views/verdicta_templates.xml",
        "views/verdicta_question_views.xml",
        "views/verdicta_intake_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
