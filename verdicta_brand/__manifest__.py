{
    "name": "Verdicta Branding",
    "summary": "Navy and gold brand on invoices, and the letterhead defaults",
    "description": """
Applies the Verdicta identity to the accounting documents.

* Puts the real logo mark on the company record. Odoo's own external report
  layout already renders ``company.logo``, so the mark then appears in the
  invoice header, in the backend and on every printed document.
* Restyles the customer invoice / credit note to the palette decoded from the
  logo: deep navy #01123C with gold #C4931C. This is a stylesheet layered over
  the standard layout rather than a rewritten template, so an update to the
  account module cannot break it.
* Seeds the letterhead (name, Dubai address, phone, email, website) on
  install, writing only fields that are still empty.
""",
    "author": "SGC TECH AI",
    "website": "https://sgctech.ai",
    "category": "Accounting",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "base",
        "account",
    ],
    "data": [
        "data/ir_cron_data.xml",
        "report/brand_invoice.xml",
        "views/company_brand_view.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
