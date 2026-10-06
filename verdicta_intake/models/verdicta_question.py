import json
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Reused across the model, the form template and the PDF report so a question
# can be retired without touching any template.
# Priority tiers. The public form shows one tab per tier so a client is never
# faced with the whole question set at once: "Start here" holds only what is
# genuinely blocking, and everything else is grouped behind its own tab.
#
#   1 = Start here    - blocking, nothing else can proceed without it
#   2 = Soon          - needed for the final accounts, but not blocking
#   3 = When you can  - helpful context, no deadline
#
# `section` still groups questions for the PDF and the backend; `priority`
# controls what the client sees first.
PRIORITIES = [
    ("1", "Start here"),
    ("2", "Soon"),
    ("3", "When you can"),
]

SECTIONS = [
    ("practice", "Practice details"),
    ("approvals", "Approvals & deadlines"),
    ("contact", "Who to contact"),
    ("bank", "Bank & cash accounts"),
    ("partners", "Partners & profit share"),
    ("staff", "Staff & payroll"),
    ("wps", "WPS & payroll compliance"),
    ("vat", "VAT registration"),
    ("einvoicing", "E-invoicing readiness"),
    ("clarifications", "Open items - our queries"),
    ("records", "Records you will send"),
    ("declaration", "Declaration"),
]

# Types that produce a box the client can actually type in.
INPUT_TYPES = [
    "char", "text", "number", "money", "date", "email", "phone",
    "select", "multiselect", "checkbox", "confirm",
]

# Types whose answer is a single tick / confirmation rather than free text.
BOOLEAN_TYPES = ["checkbox", "confirm"]


class VerdictaQuestion(models.Model):
    """A single question on the reusable intake form.

    Questions are records, not template markup, so the form can be reshaped
    from the backend without a code change or deploy.
    """

    _name = "verdicta.question"
    _description = "Verdicta Intake Question"
    _order = "section, display_order, id"
    _rec_name = "label"

    name = fields.Text(
        string="Question",
        required=True,
        help="The sentence the client reads above the input box.",
    )
    label = fields.Char(
        string="Field label",
        required=True,
        help="Short label for the input itself. Used on the PDF.",
    )
    section = fields.Selection(
        selection=SECTIONS,
        required=True,
        default="clarifications",
    )
    priority = fields.Selection(
        selection=PRIORITIES,
        string="Priority tab",
        required=True,
        default="1",
        index=True,
        help="Which tab of the public form this question appears under. "
             "'Start here' holds only what is blocking; everything else is "
             "grouped behind 'Soon' or 'When you can' so the client is not "
             "faced with the whole set at once.",
    )
    field_type = fields.Selection(
        selection=[
            ("char", "Short text"),
            ("text", "Long text"),
            ("number", "Whole number"),
            ("money", "Amount (AED)"),
            ("date", "Date"),
            ("email", "Email"),
            ("phone", "Phone"),
            ("select", "Choose one"),
            ("multiselect", "Choose several"),
            ("checkbox", "Tick every option that applies"),
            ("confirm", "Tick to confirm"),
            ("info", "Statement only - no input"),
        ],
        required=True,
        default="char",
    )
    options = fields.Text(
        string="Options",
        help="One per line. Only used by choose-one / choose-several / "
             "tick-all field types.",
    )
    help_text = fields.Text(
        string="Help text",
        help="Small print under the input box. Shown on screen and on the PDF.",
    )
    known_label = fields.Char(
        string="Known value label",
        help="Optional. Turns the question into a confirmation, e.g. "
             "'Our records show'.",
    )
    known_value = fields.Float(
        string="Known value",
        digits=(16, 2),
        help="Figure we already hold. The client confirms or corrects it.",
    )
    known_is_amount = fields.Boolean(
        string="Known value is an amount",
        default=True,
    )
    required = fields.Boolean(
        string="Required",
        default=False,
    )
    display_order = fields.Integer(
        string="Order",
        default=10,
    )
    state = fields.Selection(
        selection=[
            ("open", "Open - shown on the form"),
            ("resolved", "Resolved - hidden from every form"),
            ("retired", "Retired - no longer needed"),
        ],
        required=True,
        default="open",
        help="Setting this to Resolved hides the question from every form. "
             "Answering a question never hides it: each client is asked "
             "until they answer it, so only the desk retires a question.",
    )
    auto_close = fields.Boolean(
        string="Keep after answer",
        default=False,
        help="Untick (the default) so the question disappears from the form "
             "as soon as the client answers it. Tick to keep asking.",
    )
    internal_note = fields.Text(
        string="Internal note",
        help="For the Verdicta / SGC team only. Never rendered on the public "
             "form or the client PDF.",
    )
    active = fields.Boolean(default=True)

    answered_count = fields.Integer(
        string="Times answered",
        compute="_compute_answered_count",
    )
    last_answered_at = fields.Datetime(
        string="Last answered",
        compute="_compute_answered_count",
    )

    _section_order_unique = models.Constraint(
        "unique(section, display_order, label)",
        "Two questions in the same section cannot share both an order and a "
        "label. Change the order or the label on one of them.",
    )

    # ------------------------------------------------------------------
    # computed
    # ------------------------------------------------------------------
    @api.depends("state")
    def _compute_answered_count(self):
        answers = self.env["verdicta.answer"].sudo()
        grouped = answers._read_group(
            [("question_id", "in", self.ids)],
            groupby=["question_id"],
            aggregates=["__count", "answered_at:max"],
        )
        by_qid = {}
        for row in grouped:
        qid = row.get( question_id, [0])[0] if row.get(question_id) else 0
            by_qid[qid] = (row[__count], row.get(answered_at) or False)
        for question in self:
            count, last = by_qid.get(question.id, (0, False))
            question.answered_count = count
            question.last_answered_at = last

    # ------------------------------------------------------------------
    # helpers used by templates, the controller and the PDF report
    # ------------------------------------------------------------------
    def option_list(self):
        """Return the options of this question as a list of clean strings."""
        self.ensure_one()
        raw = self.options or ""
        parts = re.split(r"[\r\n]+", raw)
        return [p.strip() for p in parts if p.strip()]

    def is_input(self):
        """True when the question renders an input box."""
        self.ensure_one()
        return self.field_type in INPUT_TYPES

    def is_boolean(self):
        self.ensure_one()
        return self.field_type in BOOLEAN_TYPES

    def is_multi(self):
        """True when the answer is a list rather than a scalar."""
        self.ensure_one()
        return self.field_type in ("multiselect", "checkbox")

    def is_money(self):
        self.ensure_one()
        return self.field_type == "money"

    def input_name(self):
        """POST field name for this question.

        Deliberately derived from the database id so a label change can never
        break a link, a stored draft, or an in-flight submission.
        """
        self.ensure_one()
        return "q_%s" % self.id

    def known_display(self):
        """The 'our records show' figure, formatted, or False when unused."""
        self.ensure_one()
        if not self.known_label:
            return False
        if self.known_is_amount:
            return "%s AED %s" % (
                self.known_label,
                "{:,.2f}".format(self.known_value),
            )
        return self.known_label

    @api.model
    def open_questions(self, extra_domain=None):
        """Every question the public form should render, in display order.

        Includes ``info`` statements: they are read, not answered, but they
        give the client the context for the boxes around them.
        """
        domain = [("state", "=", "open"), ("active", "=", True)]
        if extra_domain:
            domain += extra_domain
        return self.search(domain)

    @api.model
    def open_input_questions(self, extra_domain=None):
        """Open questions that expect an answer - the ones that count."""
        domain = [("id", "in", self.open_questions(extra_domain).ids)]
        return self.search([("field_type", "in", INPUT_TYPES)] + domain)

    @api.model
    def questions_by_section(self, questions=None):
        """Group questions into ``[(key, label, records, n_inputs), ...]``.

        Sections that end up empty are dropped so an emptied section leaves no
        stray heading on the form. ``n_inputs`` is precomputed here rather than
        in the template, which keeps the QWeb expressions trivial.
        """
        questions = questions if questions is not None else self.open_questions()
        grouped = {}
        for question in questions:
            grouped.setdefault(question.section, self.browse())
            grouped[question.section] |= question
        out = []
        for key, label in SECTIONS:
            records = grouped.get(key)
            if records:
                n_inputs = len(records.filtered(lambda q: q.is_input()))
                out.append((key, label, records, n_inputs))
        return out

    def questions_by_priority(self, questions=None):
        """Group questions into one tab per priority tier.

        Returns ``[(key, label, sections, n_inputs, n_required), ...]`` where
        `sections` is the same ``[(key, label, records, n_inputs)]`` list that
        `questions_by_section` produces, so the template can render a tab and
        then loop sections inside it without a second pass.

        Empty tiers are dropped, so if nothing lands in "When you can" the tab
        never appears. Each tier also reports how many required inputs it still
        holds, which is what the client sees on the tab label.
        """
        questions = questions if questions is not None else self.open_questions()
        by_priority = {}
        for question in questions:
            by_priority.setdefault(question.priority, self.browse())
            by_priority[question.priority] |= question
        out = []
        for key, label in PRIORITIES:
            records = by_priority.get(key)
            if not records:
                continue
            sections = self.questions_by_section(records)
            if not sections:
                continue
            n_inputs = sum(n for _k, _l, _r, n in sections)
            n_required = len(records.filtered(
                lambda q: q.is_input() and q.required))
            out.append((key, label, sections, n_inputs, n_required))
        return out


    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        questions = super().create(vals_list)
        questions._refresh_client_counters()
        questions._wake_stakeholder_notification()
        return questions

    def write(self, vals):
        result = super().write(vals)
        # Required-ness, section or the question itself moving changes how
        # many answers every client still owes, so the stored counters have
        # to be recomputed - otherwise the client sees a stale count.
        if {"required", "active", "state", "field_type", "section"} & set(vals):
            self._refresh_client_counters()
        return result

    def _wake_stakeholder_notification(self):
        """Schedule the new-question notifier to run shortly after a question
        lands.

        The notifier batches and dedupes per intake, so a burst of questions
        added in one sitting still becomes a single email. Running it via a
        trigger two minutes out means the client hears about a new request
        within minutes instead of waiting for the half-hour safety-net sweep.
        """
        fresh = self.filtered(
            lambda q: q.state == "open" and q.active
            and q.field_type in INPUT_TYPES
        )
        if not fresh:
            return
        cron = self.env.ref(
            "verdicta_intake.ir_cron_notify_new_questions",
            raise_if_not_found=False,
        )
        if not cron or not cron.active:
            return
        cron.sudo()._trigger(
            at=fields.Datetime.now() + timedelta(minutes=2))

    def _refresh_client_counters(self):
        """A change to the question bank moves every client's progress.

        The intake helper returns early on an empty recordset, so target the
        open intakes directly rather than calling it on nothing.
        """
        Intake = self.env["verdicta.intake"].sudo()
        open_intakes = Intake.search([("state", "in", ("draft", "submitted"))])
        if open_intakes:
            open_intakes._compute_outstanding_required()

    def action_open(self):
        self.write({"state": "open"})
        self._refresh_client_counters()

    def action_resolve(self):
        self.write({"state": "resolved"})
        self._refresh_client_counters()

    def action_retire(self):
        self.write({"state": "retired", "active": False})
        self._refresh_client_counters()

    def action_restore(self):
        self.write({"state": "open", "active": True})
        self._refresh_client_counters()

    # ------------------------------------------------------------------
    @api.constrains("field_type", "options")
    def _check_options(self):
        for question in self:
            needs_options = question.field_type in (
                "select", "multiselect", "checkbox",
            )
            if needs_options and not question.option_list():
                raise ValidationError(
                    _("Question '%(label)s' is set to '%(type)s' but has no "
                      "options. Add one option per line.")
                    % {"label": question.label, "type": question.field_type}
                )
            if question.field_type in ("select", "multiselect", "checkbox"):
                dupes = [
                    opt for opt in question.option_list()
                    if question.option_list().count(opt) > 1
                ]
                if dupes:
                    raise ValidationError(
                        _("Question '%s' has duplicate options: %s")
                        % (question.label, ", ".join(sorted(set(dupes))))
                    )

    @api.constrains("known_value", "known_label")
    def _check_known(self):
        for question in self:
            if question.known_value and not question.known_label:
                raise ValidationError(
                    _("Question '%s' has a known value but no known value "
                      "label.") % question.label
                )

    @api.depends("label", "section")
    def _compute_display_name(self):
        labels = dict(SECTIONS)
        for question in self:
            question.display_name = "[%s] %s" % (
                labels.get(question.section, question.section or "?"),
                question.label or "?",
            )
