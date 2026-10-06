import base64
import os

from odoo import api, models

# The mark, bundled inside this module. Bundling means the invoice renders it
# with no read access to the company partner record - wkhtmltopdf runs as the
# service user and cannot fetch /web/image for res.partner.
LOGO_RELPATH = os.path.join("static", "src", "img", "verdicta_logo.png")

# Letterhead confirmed by the client on 30 Sep 2026. Only ever written into
# fields that are still blank. Odoo 19 has no `mobile` field on res.company or
# res.partner, so the mobile number lives in `phone`, which is what the report
# layouts read anyway.
LETTERHEAD = {
    "name": "Verdicta Legal Consultant",
    "street": "Al Saqr Business Tower",
    "city": "Dubai",
    "phone": "+971 50 481 5988",
    "email": "admin@verdictalegalconsultant.ae",
    "website": "https://www.verdictalegalconsultant.ae",
}


def _read_logo():
    path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), os.pardir, LOGO_RELPATH,
    ))
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return b""
    return raw or b""


class ResCompanyBrand(models.Model):
    """Letterhead defaults and the mark, for the active company."""

    _inherit = "res.company"

    # ------------------------------------------------------------------
    def _verdicta_logo_b64(self):
        """Base64 of the bundled mark, or False when it cannot be read."""
        self.ensure_one()
        raw = _read_logo()
        return base64.b64encode(raw) if raw else False

    def _verdicta_letterhead_address(self):
        self.ensure_one()
        return ", ".join(
            p for p in [self.street, self.city, self.country_id.name] if p
        )

    # ------------------------------------------------------------------
    @api.model
    def _verdicta_install_company_logo(self, company=None):
        """Put the mark on the company partner.

        Odoo 19 has no ``res.partner.logo``: ``res.company.logo`` is a related
        field onto ``partner_id.image_1920``, so writing that one field sets
        the logo everywhere core renders it (report headers, backend, print).
        """
        company = company or self.env.company
        raw = _read_logo()
        if not raw:
            return False
        b64 = base64.b64encode(raw)
        company.partner_id.sudo().write({"image_1920": b64})
        # the website front-end uses the separate logo_web field
        if "logo_web" in self.env["res.company"]._fields:
            company.sudo().write({"logo_web": b64})
        return True

    @api.model
    def _verdicta_blank_letterhead(self, company):
        """The LETTERHEAD entries that are both valid here and still empty.

        Filtered against the live field list so a future core rename cannot
        turn the install hook into a KeyError.
        """
        fields = self.env["res.company"]._fields
        return {
            name: value
            for name, value in LETTERHEAD.items()
            if name in fields and not (company[name] or False)
        }

    @api.model
    def _verdicta_apply_letterhead(self):
        """Fill in only the letterhead fields that are still blank."""
        company = self.env.company
        updates = self._verdicta_blank_letterhead(company)
        if updates:
            company.write(updates)
        self._verdicta_install_company_logo(company)
        return updates

    def action_reapply_brand(self):
        """Backend button: restore the mark and refill blank letterhead."""
        for company in self:
            self.env["res.company"]._verdicta_install_company_logo(company)
            updates = self.env["res.company"]._verdicta_blank_letterhead(company)
            if updates:
                company.write(updates)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Verdicta brand",
                "message": "Logo restored and blank letterhead fields filled in.",
                "type": "success",
                "sticky": False,
            },
        }

    def _cron_seed_letterhead(self):
        self.env["res.company"]._verdicta_apply_letterhead()
