import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app  # Adds this project's private dependencies for source runs.
from gui import CheckinWindow


class TajiduoLoginRoutingTests(unittest.TestCase):
    def test_game_login_uses_sms_instead_of_incompatible_web_cookie_login(self):
        window = SimpleNamespace(login_job=None, sms_tajiduo=Mock())
        module = SimpleNamespace(platform="tajiduo", name="异环")
        with patch("gui.BrowserLogin") as browser_login:
            CheckinWindow.login(window, module)
        window.sms_tajiduo.assert_called_once_with(module)
        browser_login.assert_not_called()


if __name__ == "__main__":
    unittest.main()
