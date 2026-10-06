from datetime import timedelta

from odoo import api, fields, models


class VerdictaAttempt(models.Model):
    """Rate-limit ledger for the two public routes.

    The intake form is reachable by anyone who has an access code, so both the
    code check and the "request a code" page are rate limited per IP. Rows are
    cheap, expired daily, and never store anything identifying beyond the IP.
    """

    _name = "verdicta.attempt"
    _description = "Verdicta Intake Access Attempt"
    _order = "create_date desc"

    ip = fields.Char(required=True, index=True)
    route = fields.Char(
        required=True,
        help="Which public route was hit: 'form' or 'request'.",
    )
    success = fields.Boolean(
        help="True when the access code was valid / the request was accepted.",
    )
    expires_at = fields.Datetime(
        string="Expires",
        required=True,
        index=True,
        help="Rows older than this are ignored and deleted by the purge cron.",
    )

    # ------------------------------------------------------------------
    # thresholds - raised here rather than in config because they are
    # engineering safety limits, not client-editable settings.
    # ------------------------------------------------------------------
    FORM_LIMIT = 20
    REQUEST_LIMIT = 6
    WINDOW_HOURS = 1

    @api.model
    def _window_start(self, hours=None):
        hours = hours or self.WINDOW_HOURS
        return fields.Datetime.now() - timedelta(hours=hours)

    @api.model
    def _client_ip(self, request):
        """Best-effort client IP.

        ``X-Forwarded-For`` is only trusted when the request actually arrived
        through the proxy, which is the case here (nginx -> odoo, proxy_mode
        on). The first entry is the original client.
        """
        forwarded = request.httprequest.headers.get("X-Forwarded-For") or ""
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        return request.httprequest.remote_addr or "unknown"

    @api.model
    def hit(self, request, route, success=False):
        """Record an attempt and return True if this one is still allowed."""
        ip = self._client_ip(request)
        hours = self.WINDOW_HOURS
        existing = self.sudo().search_count([
            ("ip", "=", ip),
            ("route", "=", route),
            ("create_date", ">=", self._window_start(hours)),
        ])
        limit = self.REQUEST_LIMIT if route == "request" else self.FORM_LIMIT
        self.sudo().create({
            "ip": ip,
            "route": route,
            "success": bool(success),
            "expires_at": fields.Datetime.now() + timedelta(days=1),
        })
        return existing < limit

    @api.model
    def cron_purge_expired(self):
        """Drop attempt rows past their window. Runs nightly."""
        limit = 5000
        rows = self.sudo().search(
            [("expires_at", "<", fields.Datetime.now())], limit=limit,
        )
        count = len(rows)
        rows.unlink()
        return count
