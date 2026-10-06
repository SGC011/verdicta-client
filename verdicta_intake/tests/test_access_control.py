from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError


class TestAccessControl(TransactionCase):
    """Client answers must not be readable by the public user or by ordinary
    accounting staff who can log in but are not in the Verdicta Intake group.
    """

    def setUp(self):
        super().setUp()
        self.Question = self.env["verdicta.question"]
        self.Intake = self.env["verdicta.intake"]

        self.question = self.Question.create({
            "name": "Please explain the 9,700 paid on 3 July.",
            "label": "Explain 9,700",
            "section": "clarifications",
            "field_type": "text",
        })
        self.intake = self.Intake.create({
            "practice_name": "Verdicta Legal Practice",
            "contact_email": "hossam@example.ae",
        })
        self.intake.apply_submission(
            {self.question.input_name(): "Half was a refundable advance."},
        )

        self.public = self.env["res.users"].search(
            [("share", "=", True)], limit=1,
        ) or self.env.ref("base.public_user")
        self.plain = self.env["res.users"].create({
            "name": "Plain Accountant",
            "login": "plain_accountant_test",
            "email": "plain@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.manager = self.env["res.users"].create({
            "name": "Intake Manager",
            "login": "intake_manager_test",
            "email": "manager@example.com",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref(
                    "verdicta_intake.group_verdicta_intake_manager",
                ).id,
            ])],
        })

    def test_01_public_cannot_read_answers(self):
        with self.assertRaises(AccessError):
            self.intake.with_user(self.public).read(["reference"])

    def test_02_public_cannot_read_questions(self):
        with self.assertRaises(AccessError):
            self.question.with_user(self.public).read(["label"])

    def test_03_plain_user_cannot_read_answers(self):
        with self.assertRaises(AccessError):
            self.intake.with_user(self.plain).read(["reference"])

    def test_04_plain_user_cannot_read_answer_lines(self):
        with self.assertRaises(AccessError):
            self.intake.answer_ids.with_user(self.plain).read(["value"])

    def test_05_manager_can_read(self):
        record = self.intake.with_user(self.manager).read(["reference"])
        self.assertTrue(record)
        self.assertEqual(record[0]["reference"], self.intake.reference)

    def test_06_manager_can_read_answer_text(self):
        # The manager sees the free-text answer the client actually typed.
        value = self.intake.with_user(self.manager).answer_ids[0].value
        self.assertIn("refundable advance", value)

    def test_07_manager_group_implies_user_group(self):
        # Assert the behaviour, not the ORM plumbing: has_group() is the
        # supported way to ask whether a user is in a group *including*
        # implications, whereas group_ids is only the explicitly-assigned
        # list and all_implied_ids does not reliably expand in this build.
        user_group = "verdicta_intake.group_verdicta_intake_user"
        self.assertTrue(self.manager.has_group(user_group))
        # ...and the implication is configured in the data, not just implied
        # by the ACLs.
        manager_group = self.env.ref("verdicta_intake.group_verdicta_intake_manager")
        self.assertIn(self.env.ref(user_group), manager_group.implied_ids)
        # A manager really can do everything a viewer can.
        self.intake.with_user(self.manager).write({"practice_name": "Renamed Ltd"})

    def test_08_plain_user_cannot_write_questions(self):
        with self.assertRaises(AccessError):
            self.question.with_user(self.plain).write({"label": "hacked"})

    def test_09_plain_user_cannot_create_intake(self):
        with self.assertRaises(AccessError):
            self.Intake.with_user(self.plain).create({"contact_name": "x"})

    def test_10_ordinary_user_group_does_not_grant_access(self):
        # The whole point: base.group_user is not enough.
        self.assertFalse(
            self.plain.has_group("verdicta_intake.group_verdicta_intake_user"),
        )
        with self.assertRaises(AccessError):
            self.Question.with_user(self.plain).search([])

    def test_11_access_code_required_to_reach_form(self):
        self.assertTrue(self.intake._check_access_code(self.intake.access_code))
        self.assertFalse(self.intake._check_access_code("A" * 20))
