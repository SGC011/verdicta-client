from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestQuestionEngine(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Question = self.env["verdicta.question"]
        self.bank = self.Question.create({
            "name": "How many bank accounts does the practice hold?",
            "label": "Number of bank accounts",
            "section": "bank",
            "field_type": "number",
            "display_order": 10,
        })

    def test_01_open_by_default(self):
        self.assertEqual(self.bank.state, "open")
        self.assertIn(self.bank, self.Question.open_questions())
        self.assertIn(self.bank, self.Question.open_input_questions())

    def test_02_input_name_is_id_based_and_stable(self):
        # A label change must not change the POST field name, or a link or an
        # in-flight submission breaks.
        before = self.bank.input_name()
        self.bank.label = "Bank accounts (renamed)"
        self.assertEqual(before, self.bank.input_name())
        self.assertEqual(before, "q_%s" % self.bank.id)

    def test_03_resolved_question_leaves_the_form(self):
        self.bank.action_resolve()
        self.assertNotIn(self.bank, self.Question.open_questions())
        self.assertNotIn(self.bank, self.Question.open_input_questions())

    def test_04_retire_and_restore(self):
        self.bank.action_retire()
        self.assertEqual(self.bank.state, "retired")
        self.assertFalse(self.bank.active)
        self.assertNotIn(self.bank, self.Question.open_questions())
        self.bank.action_restore()
        self.assertEqual(self.bank.state, "open")
        self.assertIn(self.bank, self.Question.open_questions())

    def test_05_info_question_renders_but_does_not_count(self):
        note = self.Question.create({
            "name": "This form is about accounting, not legal advice.",
            "label": "Please read",
            "section": "practice",
            "field_type": "info",
            "display_order": 5,
        })
        self.assertIn(note, self.Question.open_questions())
        self.assertNotIn(note, self.Question.open_input_questions())
        self.assertFalse(note.is_input())

    def test_06_options_required_for_choice_types(self):
        with self.assertRaises(ValidationError):
            self.Question.create({
                "name": "Which accounts?", "label": "Accounts",
                "section": "bank", "field_type": "select",
            })
        ok = self.Question.create({
            "name": "Which accounts?", "label": "Accounts",
            "section": "bank", "field_type": "select",
            "options": "WIO\nENBD",
        })
        self.assertEqual(ok.option_list(), ["WIO", "ENBD"])

    def test_07_duplicate_options_rejected(self):
        with self.assertRaises(ValidationError):
            self.Question.create({
                "name": "Tick", "label": "Tick",
                "section": "bank", "field_type": "checkbox",
                "options": "WIO\nWIO",
            })

    def test_08_known_value_formatting(self):
        q = self.Question.create({
            "name": "Confirm receipts", "label": "Receipts",
            "section": "clarifications", "field_type": "confirm",
            "known_label": "Our records show", "known_value": 223319.33,
        })
        self.assertIn("223,319.33", q.known_display())
        self.assertIn("AED", q.known_display())
        no_known = self.Question.create({
            "name": "Anything else?", "label": "Other",
            "section": "clarifications", "field_type": "text",
        })
        self.assertFalse(no_known.known_display())

    def test_09_known_value_without_label_rejected(self):
        with self.assertRaises(ValidationError):
            self.Question.create({
                "name": "x", "label": "x", "section": "bank",
                "field_type": "money", "known_value": 100.0,
            })

    def test_10_sections_drop_empties_and_count_inputs(self):
        Question = self.Question
        sections = Question.questions_by_section(
            Question.open_questions(),
        )
        keys = [s[0] for s in sections]
        self.assertIn("bank", keys)
        # every entry carries a 4-tuple with an input count
        for key, label, records, n_inputs in sections:
            self.assertTrue(label)
            self.assertTrue(records)
            self.assertIsInstance(n_inputs, int)
        # no duplicates, order follows the canonical section list
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, sorted(
            keys,
            key=lambda k: [kk for kk, _ in Question._fields[
                "section"].selection].index(k),
        ))

    def test_11_ordering_within_a_section(self):
        second = self.Question.create({
            "name": "Second", "label": "Second",
            "section": "bank", "field_type": "text", "display_order": 20,
        })
        first = self.Question.create({
            "name": "First", "label": "First",
            "section": "bank", "field_type": "text", "display_order": 1,
        })
        order = self.Question.open_questions().filtered(
            lambda q: q.section == "bank"
        ).ids
        self.assertLess(order.index(first.id), order.index(second.id))
