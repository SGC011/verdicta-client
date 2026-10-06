import logging
import os
import time
from xml.sax.saxutils import escape

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# A human cannot realistically complete this form faster than this, so a
# submission posted sooner is treated as a bot. Set in the template.
MIN_SECONDS_ON_FORM = 3

# A hidden field only a bot fills in. Named to attract naive autofill.
HONEYPOT_FIELD = "q_website"

# The accounting desk, as seen by the client.
#
# Sending happens on the sgctech.ai domain, not verdictalegalconsultant.ae:
# the latter's SPF authorises `_spf.google.com` only, so mail from this box
# with that From address fails SPF and is junked. sgctech.ai authorises the
# SGC relay, so it passes. The client still sees the full Verdicta company
# name because the sender carries it as the display name.
DESK_EMAIL = "info@sgctech.ai"
DESK_FROM = '"Verdicta Legal Consultant" <%s>' % DESK_EMAIL


def _client_ip():
    return request.env["verdicta.attempt"]._client_ip(request)


def _bump(route, success=False):
    return request.env["verdicta.attempt"].sudo().hit(request, route, success)


def _desk_email():
    return (request.env["ir.config_parameter"].sudo().get_param(
        "verdicta_intake.desk_email", DESK_EMAIL,
    ) or DESK_EMAIL)


def _send_request_code_email(name, practice, email):
    """Email the desk asking them to issue an access code.

    Built with mail.mail directly: there is no record to hang a
    mail.template off, and the body is short and fixed.
    """
    body = """
        <p>A new Verdicta client has asked for access to the intake form.</p>
        <table cellpadding="4" style="font-family: Arial; font-size: 13px;">
            <tr><td><b>Name</b></td><td>%s</td></tr>
            <tr><td><b>Practice</b></td><td>%s</td></tr>
            <tr><td><b>Reply-to</b></td><td>%s</td></tr>
        </table>
        <p style="margin-top: 14px;">
            To let them in, open
            <b>Accounting &rarr; Verdicta Intake &rarr; Submissions</b>,
            create a submission, and use <b>Send invite</b>. The private link
            goes to the address above.
        </p>
    """ % (escape(name or "-"), escape(practice or "-"), escape(email))
    try:
        mail = request.env["mail.mail"].sudo().create({
            "subject": "Verdicta intake - access code requested by %s"
                       % (practice or name or email),
            "body_html": body,
            "email_from": DESK_FROM,
            "email_to": _desk_email(),
            "reply_to": email,
            "auto_delete": True,
        })
        mail.send(force_send=True)
    except Exception:  # noqa: BLE001 - never leak mail errors to the client
        _logger.exception("verdicta_intake: access code request email failed")


def _compliance_doc():
    """The UAE tax & compliance recommendations, shown on the form.

    The VAT and WPS questions are driven by this document, so the client is
    given the source rather than being asked to take our word for it. Served
    straight off the module bundle, so it needs no attachment record and
    cannot be deleted by accident.
    """
    filename = "UAE-Compliance-Recommendations.pdf"
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "static", "src", "docs", filename,
    )
    if not os.path.exists(path):
        return None
    size_kb = int(round(os.path.getsize(path) / 1024.0))
    return {
        "title": "UAE Tax & Compliance Recommendations 2026",
        "note": "Read this before the VAT and payroll questions below. It "
                "explains each deadline and what it costs to miss it.",
        "cta": "Open the compliance report",
        "size": "PDF · %d KB" % size_kb,
        "url": "/verdicta_intake/static/src/docs/%s" % filename,
    }


def _brand():
    """Everything the page needs to letterhead itself.

    Read from the Odoo company record, so a change in Settings is reflected on
    the form immediately. The mark comes from the module bundle rather than
    res.partner, because the public form and wkhtmltopdf both need it without
    read access to the company partner.
    """
    company = request.env.company.sudo()
    phone = company.phone or ""
    return {
        "company": company,
        "name": company.name or "Verdicta",
        "tagline": company.country_id.name or "UAE",
        "address": ", ".join(
            p for p in [company.street, company.city, company.country_id.name] if p
        ),
        # Odoo 19 dropped `mobile` from res.company, so the one number is
        # `phone`; expose it under both keys so the template stays simple.
        "phone": phone,
        "mobile": phone,
        "email": company.email or "",
        # NB: do not name this key "website". Routes declared website=True get
        # a `website` recordset injected into the qcontext by Odoo, which would
        # shadow a string here and blow up the template with
        # "can only concatenate str (not \"website\") to str".
        "site_url": company.website or "",
        "vat": company.vat or "",
        "logo_url": "/verdicta_intake/static/src/img/verdicta_logo.png",
    }


class VerdictaIntakeController(http.Controller):

    # Browser tab title per page. Without this the shared layout falls back to
    # Odoo's own default and every public intake page is titled "Odoo Report",
    # which leaks the platform name to clients.
    _PAGE_TITLES = {
        "verdicta_intake.page_request": "Request your onboarding form",
        "verdicta_intake.page_request_sent": "Access code on its way",
        "verdicta_intake.page_form": "Client onboarding form",
        "verdicta_intake.page_done": "Thank you",
        "verdicta_intake.page_not_found": "Link not valid",
    }
    _TITLE_SUFFIX = " | Verdicta Legal Consultant"

    def _render(self, template, values=None):
        """Render one of our pages with the shared chrome in place.

        Each page template already does <t t-call="verdicta_intake.layout_intake">,
        so no layout is passed here: Odoo 19 dropped the `layout` kwarg from
        http.Response and passing it raises TypeError.

        Every public intake page carries X-Robots-Tag so client answers and
        access-code links cannot end up in a search index.
        """
        payload = dict(values or {})
        payload.setdefault("noindex", True)
        if not payload.get("title"):
            page = self._PAGE_TITLES.get(template, "Client onboarding")
            payload["title"] = page + self._TITLE_SUFFIX
        payload.update(_brand())
        response = request.render(template, payload)
        if payload.get("noindex", True):
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response

    # ------------------------------------------------------------------
    # Access code request
    # ------------------------------------------------------------------
    @http.route(
        "/onboarding", type="http", auth="public", methods=["GET"],
        website=True, sitemap=False,
    )
    def intake_request_page(self, **kw):
        """Landing page: explain the form and ask for an access code."""
        if request.params.get("sent"):
            return self._render("verdicta_intake.page_request_sent", {})
        return self._render("verdicta_intake.page_request", {})

    @http.route(
        "/onboarding/request", type="http", auth="public", methods=["GET"],
        website=True, sitemap=False,
    )
    def intake_request_page_alias(self, **kw):
        """GET on the submit URL: send the visitor to the landing page.

        Without this, a GET here does not match the POST route below, so it
        falls through to /onboarding/<string:code> with code="request" and the
        visitor is told their access code is not valid - a confusing answer to
        a perfectly reasonable URL. Declared before the /onboarding/<code>
        routes below so it wins the match.
        """
        return request.redirect("/onboarding")

    @http.route(
        "/onboarding/request", type="http", auth="public", methods=["POST"],
        website=True, csrf=True, sitemap=False,
    )
    def intake_request_submit(self, **post):
        """Ask SGC to email an access code to a named contact."""
        if not _bump("request"):
            return self._render("verdicta_intake.page_request", {
                "error": "Too many requests from this connection. "
                         "Please try again later, or email us directly.",
            })

        if post.get(HONEYPOT_FIELD):
            # Silently accept so the bot does not learn anything.
            return request.redirect("/onboarding?sent=1")

        email = (post.get("email") or "").strip()
        name = (post.get("name") or "").strip()
        practice = (post.get("practice") or "").strip()
        if not email or "@" not in email:
            return self._render("verdicta_intake.page_request", {
                "error": "Please give a valid email address.",
                "email": email,
                "name": name,
                "practice": practice,
            })

        _send_request_code_email(name, practice, email)
        return request.redirect("/onboarding?sent=1")

    # ------------------------------------------------------------------
    # The form
    # ------------------------------------------------------------------
    def _load_intake(self, code):
        """Return the intake for this code, or None.

        Deliberately returns None for both "no such code" and "wrong code" so
        the page cannot be used to probe which codes exist.
        """
        code = (code or "").strip().upper()
        if not code or len(code) < 8:
            _bump("form")
            return None
        Intake = request.env["verdicta.intake"].sudo()
        found = Intake.search([("access_code", "=", code)], limit=1)
        if not found or not found._check_access_code(code):
            _bump("form")
            return None
        return found

    def _not_found(self):
        return self._render("verdicta_intake.page_not_found", {})

    @http.route(
        "/onboarding/<string:code>", type="http", auth="public", methods=["GET"],
        website=True, sitemap=False, csrf=False,
    )
    def intake_form(self, code, **kw):
        intake = self._load_intake(code)
        if not intake:
            return self._not_found()
        if intake.state == "closed":
            return request.redirect("/onboarding/%s/done" % code)
        return self._render(
            "verdicta_intake.page_form", self._form_values(intake),
        )

    def _form_values(self, intake, errors=None, posted=None, notices=None):
        Question = request.env["verdicta.question"].sudo()
        # Only questions this intake has not already answered, so a client
        # returning sees a shorter form rather than a full repeat.
        answered = intake.answer_ids.mapped("question_id")
        questions = Question.open_questions() - answered
        return {
            "intake": intake,
            "reference": intake.reference,
            "practice": intake.practice_name or "",
            "sections": Question.questions_by_section(questions),
            "tabs": Question.questions_by_priority(questions),
            "compliance_doc": _compliance_doc(),
            "form_ts": int(time.time()),
            "answered_count": len(answered),
            "total_count": len(Question.open_input_questions()),
            "outstanding_required": intake.outstanding_required,
            "progress_pct": intake.progress_pct,
            "errors": errors or [],
            "notices": notices or [],
            "posted": posted or {},
            "csrf_token": request.csrf_token(),
        }

    @http.route(
        "/onboarding/<string:code>", type="http", auth="public", methods=["POST"],
        website=True, csrf=True, sitemap=False,
    )
    def intake_form_submit(self, code, **post):
        intake = self._load_intake(code)
        if not intake:
            return self._not_found()
        if intake.state == "closed":
            return request.redirect("/onboarding/%s/done" % code)

        # --- bot checks -------------------------------------------------
        if post.get(HONEYPOT_FIELD):
            return request.redirect("/onboarding/%s/done" % code)
        try:
            on_form_for = int(post.get("form_ts") or 0)
        except (TypeError, ValueError):
            on_form_for = 0
        if not on_form_for or (time.time() - on_form_for) < MIN_SECONDS_ON_FORM:
            return self._render("verdicta_intake.page_form", self._form_values(
                intake,
                errors=["That was submitted too quickly to be a real form "
                        "submission. Please try again."],
                posted=post,
            ))

        # --- capture ---------------------------------------------------
        ip = _client_ip()

        # 1. Signature, validated before anything is written: a change can
        #    never reach the record unattributed.
        sig_error = None
        sig_png = b""
        sig_svg = ""
        sig_name = (post.get("signer_name") or "").strip()
        sig_role = (post.get("signer_role") or "").strip()
        sig_sent = bool(
            post.get("signature_data") or post.get("signature_paths")
            or post.get("authority_confirmed")
        )
        signing = False
        if sig_sent or sig_name or sig_role:
            try:
                sig_png = intake._decode_signature_png(post.get("signature_data"))
                sig_svg = intake._clean_signature_svg(post.get("signature_paths"))
                if not sig_name:
                    raise UserError(_("Please give the full name of the person "
                                      "signing."))
                if not post.get("authority_confirmed"):
                    raise UserError(_("The signer has to confirm they are "
                                      "authorised to submit for the practice."))
                signing = intake.signature_needs_update(
                    sig_name, sig_role, sig_png, sig_svg)
            except UserError as err:
                sig_error = str(err)

        if sig_error:
            _bump("form", success=False)
            return self._render("verdicta_intake.page_form", self._form_values(
                intake, errors=[sig_error], posted=post,
            ))

        # 2. Documents sent with this save. A refused file does not block the
        #    answers - it is reported after the save so the client can retry
        #    the upload without losing their work.
        uploads = {}
        for slot in intake.document_slots():
            picked = [
                f for f in (request.httprequest.files.getlist(slot["field"])
                            or []) if f and f.filename
            ]
            if picked:
                uploads[slot["key"]] = picked
        doc_problems = []
        stored_docs = []
        if uploads:
            try:
                stored_docs, doc_problems = intake.store_client_uploads(uploads)
            except Exception:  # noqa: BLE001
                _logger.exception("verdicta_intake: upload failed for %s",
                                  intake.reference)
                doc_problems = ["We could not store that file. Please try again."]

        # 3. What would this save actually change?
        pending_count = len(intake.pending_answer_changes(post)) + len(stored_docs)

        # The rule: nothing changed on the form, so nothing is triggered.
        if not pending_count:
            _bump("form", success=True)
            _logger.info(
                "verdicta_intake: %s saved with no changes, nothing triggered",
                intake.reference,
            )
            return self._render("verdicta_intake.page_form", self._form_values(
                intake,
                errors=doc_problems,
                notices=["Nothing to save - your answers are already up to "
                         "date, so nothing has been sent."] if not doc_problems else [],
                posted=post,
            ))

        # The rule: every change needs a signature before it can be saved.
        if not signing:
            _bump("form", success=False)
            return self._render("verdicta_intake.page_form", self._form_values(
                intake,
                errors=doc_problems + [
                    "Before you can save these changes we need a signature. "
                    "Draw your signature in the box, give your full name and "
                    "tick the authority confirmation - then save again. "
                    "(%d change(s) waiting.)" % pending_count,
                ],
                posted=post,
            ))

        try:
            _saved, _closed, errors, _stored = intake.apply_submission(
                post, ip=ip, signed=True,
                touched=bool(stored_docs or signing))
        except Exception:  # noqa: BLE001
            _logger.exception("verdicta_intake: submission failed for %s",
                              intake.reference)
            return self._render("verdicta_intake.page_form", self._form_values(
                intake,
                errors=["Something went wrong saving your answers. Nothing has "
                        "been lost - please try again."],
                posted=post,
            ))

        # Rejected files are reported with the save, not instead of it.
        errors.extend(doc_problems)

        # --- signature / authority ------------------------------------
        # Stamped after the answers are written, so the seal covers exactly
        # what was submitted. A signature only counts when it differs from
        # the one already on file.
        try:
            intake.action_sign_submission(
                name=sig_name,
                role=sig_role,
                signature_png=sig_png,
                signature_svg=sig_svg,
                ip=ip,
                authority=True,
            )
        except UserError as err:
            # Undo the save rather than leave changes on the record with no
            # signature: an unsigned change must never be recorded.
            _bump("form", success=False)
            request.env.cr.rollback()
            return self._render("verdicta_intake.page_form", self._form_values(
                intake, errors=[str(err)], posted=post,
            ))

        changed = bool(_stored or _closed or stored_docs or signing)

        # The rule: a signature, a fresh PDF and the emails go out only when
        # the save actually changed something. Clicking Save on an untouched
        # form triggers nothing at all.
        if changed:
            try:
                intake.action_generate_pdf()
                # Partial saves count too: the subject carries the
                # outstanding count so the desk always knows where it stands.
                intake.action_notify_sgc()
                intake.action_send_acknowledgement()
            except Exception:  # noqa: BLE001
                # A mail or PDF problem must not lose the answers saved.
                _logger.exception(
                    "verdicta_intake: answers saved for %s but PDF/email failed",
                    intake.reference,
                )

        if errors:
            return self._render("verdicta_intake.page_form", self._form_values(
                intake, errors=errors, posted=post,
            ))

        if intake.state == "closed":
            return request.redirect("/onboarding/%s/done" % code)
        return self._render("verdicta_intake.page_form", self._form_values(
            intake,
            notices=["Saved. A copy has been emailed to our accounting desk "
                     "with your answers and your signature."],
            posted=post,
        ))

    # ------------------------------------------------------------------
    @http.route(
        "/onboarding/<string:code>/done", type="http", auth="public",
        methods=["GET"], website=True, sitemap=False,
    )
    def intake_done(self, code, **kw):
        intake = self._load_intake(code)
        if not intake:
            return self._not_found()
        return self._render("verdicta_intake.page_done", {
            "intake": intake,
            "reference": intake.reference,
            "outstanding": intake.outstanding_required,
            "progress_pct": intake.progress_pct,
        })

    @http.route(
        "/onboarding/<string:code>/documents", type="http", auth="public",
        methods=["GET"], website=True, sitemap=False,
    )
    def intake_documents(self, code, **kw):
        """List of the documents the client uploaded, behind the access code."""
        intake = self._load_intake(code)
        if not intake:
            return self._not_found()
        missing = intake._missing_required_documents()
        return self._render("verdicta_intake.page_documents", {
            "intake": intake,
            "reference": intake.reference,
            "documents": intake._documents_received(),
            "missing": missing,
            "missing_label": ", ".join(missing),
        })

    @http.route(
        "/onboarding/<string:code>/documents/<int:att_id>", type="http",
        auth="public", methods=["GET"], website=True, sitemap=False,
    )
    def intake_document_download(self, code, att_id, **kw):
        """Download one uploaded document, gated by the intake access code."""
        intake = self._load_intake(code)
        if not intake:
            return request.not_found()
        att = intake._client_attachments().browse(att_id).exists()
        if not att:
            return request.not_found()
        return request.make_response(att.raw, [
            ("Content-Type", att.mimetype or "application/octet-stream"),
            ("Content-Length", str(len(att.raw or b""))),
            ("Content-Disposition", 'attachment; filename="%s"'
             % (att.name or "document").replace('"', "")),
            ("Cache-Control", "no-store"),
        ])

    @http.route(
        "/onboarding/<string:code>/signature.png", type="http", auth="public",
        methods=["GET"], website=True, sitemap=False,
    )
    def intake_signature(self, code, **kw):
        """The submitter's signature, for the stamped report.

        Gated by the intake access code - the same secret that opens the
        form - and never cached, so a re-signed record serves the new
        signature straight away.
        """
        intake = self._load_intake(code)
        if not intake or not intake.signature:
            return request.not_found()
        return request.make_response(intake.sudo().signature, [
            ("Content-Type", "image/png"),
            ("Cache-Control", "no-store"),
        ])

    @http.route(
        "/onboarding/<string:code>/pdf", type="http", auth="public",
        methods=["GET"], website=True, sitemap=False,
    )
    def intake_pdf(self, code, **kw):
        """Download (or refresh) the client's own copy of the PDF.

        Guarded by the access code, exactly like the form itself.
        """
        intake = self._load_intake(code)
        if not intake:
            return request.not_found()
        attachment = intake.pdf_attachment_id
        if not attachment or kw.get("refresh"):
            attachment = intake.action_generate_pdf()
        filename = attachment.name or ("%s.pdf" % intake.reference)
        return request.make_response(
            attachment.raw,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(attachment.raw))),
                ("Content-Disposition",
                 'attachment; filename="%s"' % filename),
                ("Cache-Control", "no-store"),
                ("X-Robots-Tag", "noindex, nofollow"),
            ],
        )
