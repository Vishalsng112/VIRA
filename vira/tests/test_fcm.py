"""FCM HTTP v1 sender: JWT exchange and message payload."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from vira.push.fcm import FCMSender


class FCMSenderTests(unittest.TestCase):
    def _account(self, directory: Path) -> Path:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        path = directory / "service-account.json"
        path.write_text(json.dumps({
            "type": "service_account",
            "project_id": "vira-test",
            "client_email": "vira@example.test",
            "private_key": pem,
            "token_uri": "https://oauth2.googleapis.com/token",
        }), encoding="utf-8")
        return path

    def test_send_exchanges_jwt_and_posts_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender = FCMSender(str(self._account(Path(tmp))))
            with mock.patch(
                "vira.push.fcm._post",
                side_effect=[
                    {"access_token": "access-123", "expires_in": 3600},
                    {},
                ],
            ) as post:
                ok = sender.send(
                    "device-token", "Morning brief", "Today: review the plan.",
                    {"schedule_id": "s1", "run_id": "r1"})
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 2)
        token_url = post.call_args_list[0].args[0]
        self.assertEqual(token_url, "https://oauth2.googleapis.com/token")
        send_url = post.call_args_list[1].args[0]
        self.assertIn("/projects/vira-test/messages:send", send_url)
        payload = json.loads(post.call_args_list[1].args[1])
        self.assertEqual(payload["message"]["token"], "device-token")
        self.assertEqual(payload["message"]["notification"]["title"], "Morning brief")
        self.assertEqual(payload["message"]["data"]["schedule_id"], "s1")
        self.assertEqual(
            post.call_args_list[1].args[2]["Authorization"], "Bearer access-123")

    def test_send_many_counts_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            sender = FCMSender(str(self._account(Path(tmp))))
            with mock.patch.object(
                sender, "send", side_effect=[True, False, True]
            ):
                result = sender.send_many(["a", "b", "c"], "T", "B")
        self.assertEqual(result, {"sent": 2, "failed": 1})


if __name__ == "__main__":
    unittest.main()
