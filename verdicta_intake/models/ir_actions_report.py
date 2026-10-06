from odoo import models


class IrActionsReport(models.Model):
    """Force UTF-8 when Odoo hands report HTML to wkhtmltopdf.

    The report bodies are UTF-8 encoded, but the minimal-layout wrapper
    used for PDF rendering carries no charset declaration. wkhtmltopdf
    then falls back to Latin-1, mangling every non-ASCII character (em
    dashes, middle dots, accents) in the produced PDF. Passing --encoding
    makes the input charset explicit for bodies, headers and footers.
    """

    _inherit = "ir.actions.report"

    def _build_wkhtmltopdf_args(self, paperformat_id, landscape,
                                specific_paperformat_args=None,
                                set_viewport_size=False):
        args = super()._build_wkhtmltopdf_args(
            paperformat_id, landscape,
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=set_viewport_size,
        )
        if "--encoding" not in args:
            args += ["--encoding", "utf-8"]
        return args
