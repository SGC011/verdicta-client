from odoo import api, fields, models


class VerdictaAnswer(models.Model):
    """One answered question, snapshotted at the moment it was given.

    The label, section and options are copied onto the row so the PDF keeps
    showing what was actually asked even after the question itself is edited
    or retired.
    """

    _name = "verdicta.answer"
    _description = "Verdicta Intake Answer"
    _order = "answered_at desc, id desc"
    _rec_name = "display_label"

    intake_id = fields.Many2one(
        comodel_name="verdicta.intake",
        string="Submission",
        required=True,
        ondelete="cascade",
        index=True,
    )
    question_id = fields.Many2one(
        comodel_name="verdicta.question",
        string="Question",
        required=False,
        ondelete="set null",
        index=True,
        help="Empty only if the question record was deleted outright. The "
             "snapshot fields below are what the PDF renders, so the history "
             "survives either way.",
    )
    # snapshot
    question_label = fields.Char(
        string="Question label",
        required=True,
    )
    question_text = fields.Text(
        string="Question text",
    )
    section = fields.Char(
        string="Section",
    )
    known_display = fields.Char(
        string="Known value shown",
        help="Snapshot of the figure we already held, so the PDF still shows "
             "what the client was confirming.",
    )
    value = fields.Text(
        string="Value",
        help="Plain text. Lists are stored comma separated.",
    )
    values_list = fields.Char(
        string="Values",
        help="Comma separated, for multi-select answers.",
    )
    answered_at = fields.Datetime(
        string="Answered",
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    submit_no = fields.Integer(
        string="Submission #",
        default=1,
    )
    submit_ip = fields.Char(
        string="IP",
    )

    display_label = fields.Char(compute="_compute_display_label")

    @api.depends("question_label", "value")
    def _compute_display_label(self):
        for answer in self:
            answer.display_label = "%s: %s" % (
                answer.question_label or "-",
                (answer.value or "-")[:60],
            )

    @api.model
    def _render_value(self, question, raw):
        """Normalise a raw POST value into the text we store.

        Returns ``(scalar_text, comma_separated_list)``; exactly one is
        meaningful depending on the question type.
        """
        if question.is_multi():
            if isinstance(raw, (list, tuple)):
                items = [str(v).strip() for v in raw]
            else:
                items = [i.strip() for i in str(raw or "").split(",")]
            items = [i for i in items if i]
            return ", ".join(items), ", ".join(items)
        if question.field_type == "checkbox" or question.field_type == "confirm":
            return ("Yes" if raw else ""), ""
        if question.field_type == "money" or question.field_type == "number":
            cleaned = str(raw or "").strip().replace(",", "")
            if not cleaned:
                return "", ""
            try:
                amount = float(cleaned)
            except ValueError:
                # Keep whatever the client typed rather than losing it.
                return cleaned, ""
            if question.field_type == "money":
                return "{:,.2f}".format(amount), ""
            return str(int(amount) if amount == int(amount) else amount), ""
        return (raw or "").strip(), ""
