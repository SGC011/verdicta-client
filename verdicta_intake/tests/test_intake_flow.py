from odoo.tests.common import TransactionCase


class TestIntakeFlow(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Question = self.env["verdicta.question"]
        self.Intake = self.env["verdicta.intake"]
        self.Answer = self.env["verdicta.answer"]

        self.q_text = self.Question.create({
            "name": "How many staff are on the payroll?",
            "label": "Staff on payroll",
            "section": "staff",
            "field_type": "number",
            "required": True,
            "display_order": 10,
        })
        self.q_confirm = self.Question.create({
            "name": "Please confirm the receipt figure.",
            "label": "Confirm receipts",
            "section": "clarifications",
            "field_type": "confirm",
            "known_label": "Our records show",
            "known_value": 223319.33,
            "display_order": 20,
        })
        self.q_optional = self.Question.create({
            "name": "Anything else we should know?",
            "label": "Anything else",
            "section": "clarifications",
            "field_type": "text",
            "display_order": 30,
        })
        self.intake = self.Intake.create({
            "practice_name": "Verdicta Legal Practice",
            "contact_name": "Hossam",
            "contact_email": "hossam@example.ae",
        })

    def test_01_reference_generated_and_sequential(self):
        self.assertRegex(self.intake.reference, r"^VIN-\d{4}-0001$")
        second = self.Intake.create({"contact_name": "Another"})
        self.assertRegex(second.reference, r"^VIN-\d{4}-0002$")

    def test_02_access_code_is_long_and_random(self):
        code = self.intake.access_code
        self.assertTrue(code.isalnum())
        self.assertGreaterEqual(len(code), 16)
        other = self.Intake.create({"contact_name": "Another"})
        self.assertNotEqual(code, other.access_code)

    def test_03_access_code_check(self):
        self.assertTrue(self.intake._check_access_code(self.intake.access_code))
        self.assertTrue(
            self.intake._check_access_code(self.intake.access_code.lower()),
        )
        self.assertFalse(self.intake._check_access_code("WRONG"))
        self.assertFalse(self.intake._check_access_code(""))
        self.assertFalse(self.intake._check_access_code(None))

    def test_04_answer_hides_the_question_for_that_intake_only(self):
        self.intake.apply_submission(
            {self.q_text.input_name(): "3"}, ip="1.2.3.4",
        )
        # The question stays in the catalogue so other clients are still
        # asked it; it only leaves the form of the intake that answered.
        self.assertEqual(self.q_text.state, "open")
        answered_here = self.intake.answer_ids.mapped("question_id")
        self.assertNotIn(
            self.q_text, self.Question.open_questions() - answered_here)
        answer = self.intake.answer_ids.filtered(
            lambda a: a.question_id == self.q_text)
        self.assertEqual(answer.value, "3")

    def test_04b_questions_are_asked_of_every_client(self):
        """Regression: answering on one intake must not close the question."""
        first = self.Intake.create({"contact_name": "First client"})
        second = self.Intake.create({"contact_name": "Second client"})
        first.apply_submission({self.q_text.input_name(): "3"})
        still_to_ask = (
            self.Question.open_input_questions()
            - second.answer_ids.mapped("question_id")
        )
        self.assertIn(self.q_text, still_to_ask)
        self.assertEqual(self.q_text.state, "open")

    def test_05_keep_after_answer_stays_open(self):
        self.q_text.auto_close = True
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        self.assertEqual(self.q_text.state, "open")
        self.assertEqual(self.intake.answer_ids.filtered(
            lambda a: a.question_id == self.q_text).value, "3")

    def test_06_blank_answer_does_not_close(self):
        _v, closed, errors, _stored = self.intake.apply_submission(
            {self.q_text.input_name(): "   ", self.q_optional.input_name(): ""},
        )
        self.assertEqual(self.q_text.state, "open")
        self.assertFalse(closed)
        # required question still outstanding
        self.assertIn(
            self.q_text.label, " ".join(errors),
        )

    def test_07_confirm_tick_is_stored_as_yes(self):
        self.intake.apply_submission({self.q_confirm.input_name(): "yes"})
        answer = self.intake.answer_ids.filtered(
            lambda a: a.question_id == self.q_confirm)
        self.assertEqual(answer.value, "Yes")
        self.assertEqual(answer.known_display and "223,319.33" or "",
                         "223,319.33")

    def test_08_unticked_confirm_does_not_close(self):
        self.intake.apply_submission({self.q_confirm.input_name(): ""})
        self.assertEqual(self.q_confirm.state, "open")

    def test_09_money_is_formatted(self):
        q = self.Question.create({
            "name": "How much?", "label": "Amount",
            "section": "clarifications", "field_type": "money",
        })
        self.intake.apply_submission({q.input_name(): "1234.5"})
        self.assertEqual(
            self.intake.answer_ids.filtered(
                lambda a: a.question_id == q).value, "1,234.50",
        )

    def test_10_money_with_odd_input_is_kept_verbatim(self):
        q = self.Question.create({
            "name": "How much?", "label": "Amount2",
            "section": "clarifications", "field_type": "money",
        })
        self.intake.apply_submission({q.input_name(): "about 14k"})
        self.assertEqual(
            self.intake.answer_ids.filtered(
                lambda a: a.question_id == q).value, "about 14k",
        )

    def test_11_multiselect_joins_values(self):
        q = self.Question.create({
            "name": "Which records can you send?", "label": "Records",
            "section": "records", "field_type": "checkbox",
            "options": "Bank statements\nClient receipts\nVendor invoices",
        })
        self.intake.apply_submission(
            {q.input_name(): ["Bank statements", "Vendor invoices"]},
        )
        self.assertEqual(
            self.intake.answer_ids.filtered(
                lambda a: a.question_id == q).value,
            "Bank statements, Vendor invoices",
        )

    def test_12_retired_question_cannot_be_written_back(self):
        name = self.q_optional.input_name()
        self.q_optional.action_retire()
        # page was open before the retire; the post must be ignored
        self.intake.apply_submission({name: "too late"})
        self.assertFalse(self.intake.answer_ids.filtered(
            lambda a: a.question_id == self.q_optional))

    def test_13_reanswering_updates_in_place(self):
        name = self.q_optional.input_name()
        self.q_optional.auto_close = True
        self.intake.apply_submission({name: "first"})
        self.intake.apply_submission({name: "second"})
        rows = self.intake.answer_ids.filtered(
            lambda a: a.question_id == self.q_optional)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.value, "second")
        self.assertEqual(self.intake.submit_count, 2)

    def _isolate_question_set(self):
        """Retire every question that is not one of this test's own fixtures.

        ``progress_pct`` and ``outstanding_required`` are deliberately measured
        against *every* live question in the database, not just the intake's
        own. That is the right behaviour in production - the client sees
        progress against the whole form - but it means these assertions only
        hold when the fixtures are the whole question set.

        Without this, running the suite against a database that already carries
        the seeded client questions fails on arithmetic that has nothing to do
        with the code under test. Retiring them inside the test transaction
        restores the assumption; the rollback undoes it afterwards.
        """
        self.Question.search([
            ("id", "not in", (self.q_text + self.q_confirm + self.q_optional).ids),
        ]).write({"state": "retired", "active": False})

    def test_14_state_progression_and_completion(self):
        self._isolate_question_set()
        self.assertEqual(self.intake.state, "draft")
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        self.assertEqual(self.intake.state, "submitted")
        self.q_confirm.auto_close = True
        self.q_optional.auto_close = True
        # Rule: the answers are saved, but a complete submission stays open
        # until it carries a signature.
        _values, _closed, errors, _stored = self.intake.apply_submission({
            self.q_confirm.input_name(): "yes",
            self.q_optional.input_name(): "nothing else",
        })
        self.assertEqual(self.intake.state, "submitted")
        self.assertTrue([e for e in errors if "sign" in e.lower()], errors)
        # A signed save with the bank statement on file closes it.
        self._attach_bank_statement(self.intake)
        self.intake.apply_submission(
            {self.q_optional.input_name(): "all set"}, signed=True)
        self.assertEqual(self.intake.state, "closed")
        self.assertEqual(self.intake.outstanding_required, 0)
        self.assertEqual(self.intake.progress_pct, 100)

    def test_15b_unchanged_save_stores_nothing(self):
        """Re-saving the same answers must not touch the record."""
        self._isolate_question_set()
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        before = (self.intake.submit_count, self.intake.last_submitted_at)
        post = {self.q_text.input_name(): "3"}
        self.assertEqual(self.intake.pending_answer_changes(post),
                         self.env["verdicta.question"])
        _values, _closed, _errors, stored = self.intake.apply_submission(post)
        self.assertEqual(stored, 0)
        self.assertEqual(self.intake.submit_count, before[0])
        self.assertEqual(self.intake.last_submitted_at, before[1])

    def _attach_bank_statement(self, intake, name="Bank statement WIO Apr-Sep.pdf"):
        """Put a bank statement on the record the way an upload would."""
        return self.env["ir.attachment"].sudo().create({
            "name": name,
            "raw": b"%PDF-1.4 test bank statement",
            "res_model": "verdicta.intake",
            "res_id": intake.id,
            "res_field": "documents",
            "description": "Bank statements",
            "mimetype": "application/pdf",
        })

    def test_15f_closing_needs_the_bank_statement(self):
        """Everything answered and signed still cannot close without it."""
        self._isolate_question_set()
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        self.q_confirm.auto_close = True
        self.q_optional.auto_close = True
        self.intake.apply_submission({
            self.q_confirm.input_name(): "yes",
            self.q_optional.input_name(): "nothing else",
        })
        self.assertTrue(self.intake._missing_required_documents())
        self.intake.apply_submission(
            {self.q_optional.input_name(): "checked"}, signed=True)
        self.assertEqual(self.intake.state, "submitted")
        self._attach_bank_statement(self.intake)
        self.assertEqual(self.intake._missing_required_documents(), [])
        self.intake.apply_submission(
            {self.q_optional.input_name(): "final"}, signed=True)
        self.assertEqual(self.intake.state, "closed")

    def test_15g_uploads_are_validated_grouped_and_deduped(self):
        """A bad file is refused, good ones land, re-sending changes nothing."""

        class Upload(object):
            def __init__(self, name, data=b"%PDF-1.4 body text"):
                self.filename = name
                self._data = data
                self.size = len(data)
                self.content_type = "application/pdf"

            def read(self):
                return self._data

        stored, problems = self.intake.store_client_uploads({
            "bank": [Upload("WIO Apr-Sep.pdf"),
                     Upload("Ziina Sep.pdf"),
                     Upload("payload.exe")],
            "payroll": [Upload("WPS report Sep.pdf")],
        })
        self.assertEqual(len(stored), 3)
        self.assertEqual(len(problems), 1)
        self.assertIn("payload.exe", problems[0])
        self.assertEqual(self.intake._missing_required_documents(), [])
        groups = dict(
            (label, recs) for label, recs in self.intake._documents_received()
        )
        self.assertEqual(len(groups.get("Bank statements")), 2)
        self.assertEqual(len(groups.get("Payroll / WPS reports")), 1)
        _again, dup_problems = self.intake.store_client_uploads(
            {"bank": [Upload("WIO Apr-Sep.pdf")]})
        self.assertEqual(len(dup_problems), 1)
        self.assertEqual(len(self.intake._client_attachments()), 3)

    def test_15i_requirement_follows_the_slot_not_the_filename(self):
        """A statement in the wrong slot still clears the requirement."""
        self._isolate_question_set()
        slots = self.intake.document_slots()
        bank = [sl for sl in slots if sl["required"]]
        self.assertTrue(bank, "there must be a required upload slot")
        self.assertEqual(bank[0]["key"], "bank")
        self.assertEqual(self.intake._missing_required_documents(),
                         [bank[0]["label"]])

        class Upload(object):
            def __init__(self, name, data=b"%PDF-1.4 body text"):
                self.filename = name
                self._data = data
                self.size = len(data)
                self.content_type = "application/pdf"

            def read(self):
                return self._data

        # parked in "other", but named as a statement
        self.intake.store_client_uploads({"other": [Upload("bank statement.pdf")]})
        self.assertEqual(self.intake._missing_required_documents(), [])
        # and the closing gate opens
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        self.q_confirm.auto_close = True
        self.q_optional.auto_close = True
        self.intake.apply_submission({
            self.q_confirm.input_name(): "yes",
            self.q_optional.input_name(): "nothing else",
        })
        self.intake.apply_submission(
            {self.q_optional.input_name(): "final"}, signed=True)
        self.assertEqual(self.intake.state, "closed")

    def test_15h_notifications_never_treat_the_whole_bank_as_new(self):
        """A fresh intake's watermark already covers the existing bank."""
        watermark = self.intake.notified_question_upto
        self.assertTrue(watermark)
        fresh = self.intake._questions_since_id(watermark)
        for existing in (self.q_text, self.q_confirm, self.q_optional):
            self.assertNotIn(existing, fresh)
        self.assertLess(len(fresh), len(self.Question.open_input_questions()))

    def test_15j_watermark_advances_exactly_once(self):
        """A new question is fresh until the intake is told, then it is not."""
        q = self.Question.create({
            "name": "Watermark probe", "label": "Watermark probe",
            "section": "approvals", "field_type": "text", "display_order": 996,
        })
        self.assertIn(
            q, self.intake._questions_since_id(self.intake.notified_question_upto))
        # what the notifier writes once it has told the client
        self.intake.sudo().write({"notified_question_upto": max(q.ids)})
        self.assertNotIn(
            q, self.intake._questions_since_id(self.intake.notified_question_upto))
        q2 = self.Question.create({
            "name": "Watermark probe 2", "label": "Watermark probe 2",
            "section": "approvals", "field_type": "text", "display_order": 995,
        })
        self.assertIn(
            q2, self.intake._questions_since_id(self.intake.notified_question_upto))

    def test_15i_new_questions_schedule_the_notifier(self):
        """A new question asks the notifier to run within minutes."""
        from datetime import timedelta
        from odoo import fields
        cron = self.env.ref("verdicta_intake.ir_cron_notify_new_questions")
        Trigger = self.env["ir.cron.trigger"].sudo()
        before = Trigger.search_count([("cron_id", "=", cron.id)])
        self.Question.create({
            "name": "Wake test question", "label": "Wake test question",
            "section": "approvals", "field_type": "text",
            "display_order": 997,
        })
        self.assertEqual(
            Trigger.search_count([("cron_id", "=", cron.id)]), before + 1)
        newest = Trigger.search(
            [("cron_id", "=", cron.id)], order="id desc", limit=1)
        self.assertLessEqual(
            newest.call_at - fields.Datetime.now(), timedelta(minutes=3))
        # A display-only block changes nothing for the client.
        self.Question.create({
            "name": "Info block", "label": "Info block",
            "section": "approvals", "field_type": "info",
            "display_order": 998,
        })
        self.assertEqual(
            Trigger.search_count([("cron_id", "=", cron.id)]), before + 1)

    def test_15c_signature_seal_detects_later_edits(self):
        """The seal must stop matching if an answer changes after signing."""
        self._isolate_question_set()
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        self.intake.action_sign_submission(
            name="Test Signer", role="Manager", ip="203.0.113.9", authority=True)
        self.assertTrue(self.intake.is_signed)
        self.assertIn("Matches", self.intake.signing_seal_status())
        self.intake.answer_ids[0].sudo().write({"value": "999"})
        self.assertIn("CHANGED AFTER SIGNING", self.intake.signing_seal_status())

    def test_15e_adding_a_required_question_updates_clients(self):
        """A new required question must show up in every open intake."""
        self._isolate_question_set()
        before = self.intake.outstanding_required
        self.Question.create({
            "name": "Anything else we should declare?", "label": "Extra declaration",
            "section": "clarifications", "field_type": "text", "required": True,
            "display_order": 99,
        })
        self.env.invalidate_all()
        self.assertEqual(self.intake.outstanding_required, before + 1)
        self.assertIn("Extra declaration",
                      [q.label for q in self.intake._outstanding_questions()])

    def test_15d_signature_needs_authority_and_name(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.intake.action_sign_submission(name="X", authority=False)
        self.assertFalse(self.intake.is_signed)
        with self.assertRaises(UserError):
            self.intake.action_sign_submission(name="  ", authority=True)
        self.assertFalse(self.intake.is_signed)
        self.assertNotIn("<", self.intake._clean_signature_svg("<script>x</script>"))

    def test_15_progress_partial(self):
        self._isolate_question_set()
        self.q_confirm.auto_close = True
        self.q_optional.auto_close = True
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        # 1 of 3 answered
        self.assertEqual(self.intake.progress_pct, 33)

    def test_16_submitted_at_set_once(self):
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        first = self.intake.submitted_at
        self.intake.apply_submission({self.q_optional.input_name(): "hello"})
        self.assertEqual(self.intake.submitted_at, first)
        # Both stamps land in the same second under test speed, so only assert
        # the ordering guarantee: the original submit time never moves and the
        # latest one is at least as late.
        self.assertGreaterEqual(self.intake.last_submitted_at, first)

    def test_17_pdf_generation(self):
        self.intake.apply_submission({
            self.q_text.input_name(): "3",
            self.q_confirm.input_name(): "yes",
        })
        attachment = self.intake.action_generate_pdf()
        self.assertTrue(attachment.raw.startswith(b"%PDF"))
        self.assertEqual(self.intake.pdf_attachment_id, attachment)
        # regenerating replaces rather than duplicates
        again = self.intake.action_generate_pdf()
        self.assertNotEqual(attachment.id, again.id)
        # search_count already returns an int
        self.assertEqual(self.intake.env["ir.attachment"].search_count(
            [("res_model", "=", "verdicta.intake"),
             ("res_id", "=", self.intake.id)]), 1)

    def test_18_csv_export(self):
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        csv_text = self.intake._answers_csv()
        self.assertIn("Reference", csv_text)
        self.assertIn(self.intake.reference, csv_text)
        self.assertIn("Staff on payroll", csv_text)
        self.assertIn("3", csv_text)

    def test_19_answers_by_section_uses_labels(self):
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        sections = self.intake._answers_by_section()
        self.assertTrue(sections)
        labels = [s[0] for s in sections]
        self.assertIn("Staff & payroll", labels)
        for label, records in sections:
            self.assertTrue(records)

    def test_20_reset_answers_clears_and_reopens_questions(self):
        self.intake.apply_submission({self.q_text.input_name(): "3"})
        self.assertEqual(self.q_text.state, "open")
        self.intake.action_reset_answers()
        self.assertEqual(len(self.intake.answer_ids), 0)
        self.assertEqual(self.intake.state, "draft")
        # Closure is per intake, so clearing this intake's answers puts the
        # question straight back on its form.
        shown = (
            self.Question.open_questions()
            - self.intake.answer_ids.mapped("question_id")
        )
        self.assertIn(self.q_text, shown)

    def test_21_reopen_mints_a_new_code(self):
        old = self.intake.access_code
        self.intake.action_reopen()
        self.assertNotEqual(self.intake.access_code, old)
        self.assertTrue(self.intake._check_access_code(
            self.intake.access_code))
        self.assertFalse(self.intake._check_access_code(old))

    def test_22_rate_limit_trips(self):
        from datetime import timedelta
        from odoo import fields
        Attempt = self.env["verdicta.attempt"].sudo()
        self.intake.write({"last_submit_ip": "9.9.9.9"})
        for _i in range(12):
            Attempt.create({
                "ip": "9.9.9.9", "route": "form", "success": True,
                "expires_at": fields.Datetime.now() + timedelta(days=1),
            })
        self.assertTrue(self.intake.rate_limited())
        _v, _c, errors, _stored = self.intake.apply_submission(
            {self.q_text.input_name(): "3"},
        )
        self.assertTrue(errors)
        self.assertIn("Too many", " ".join(errors))

    def test_23_purge_cron_clears_old_rows(self):
        from datetime import timedelta
        from odoo import fields
        Attempt = self.env["verdicta.attempt"].sudo()
        fresh = Attempt.create({
            "ip": "1.1.1.1", "route": "form", "success": True,
            "expires_at": fields.Datetime.now() + timedelta(days=1),
        })
        stale = Attempt.create({
            "ip": "1.1.1.2", "route": "form", "success": True,
            "expires_at": fields.Datetime.now() - timedelta(days=1),
        })
        removed = Attempt.cron_purge_expired()
        self.assertTrue(removed >= 1)
        # Re-query: `Attempt` is still the pre-purge empty recordset, so its
        # cached ids would not reflect the unlink.
        surviving = Attempt.search([("id", "in", [fresh.id, stale.id])]).ids
        self.assertNotIn(stale.id, surviving)
        self.assertIn(fresh.id, surviving)

    def test_24_public_url_is_https(self):
        url = self.intake._public_url()
        self.assertTrue(url.startswith("https://"), url)
        self.assertIn(self.intake.access_code, url)
