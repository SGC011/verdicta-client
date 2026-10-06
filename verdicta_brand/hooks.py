from odoo import SUPERUSER_ID, api


def post_init_hook(env):
    """Seed the letterhead and the mark as soon as the module is installed.

    Runs against the active company only, and fills just the fields that are
    still empty, so nothing an operator has since typed is overwritten.
    """
    if not hasattr(env, "cr"):
        env = api.Environment(env.cr, SUPERUSER_ID, {})
    env["res.company"]._verdicta_apply_letterhead()
