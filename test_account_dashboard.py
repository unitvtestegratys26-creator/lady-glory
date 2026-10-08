import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import account_api
import dashboard_server
from Main import _public_image_url, process_account_credentials


class AccountApiTests(unittest.IsolatedAsyncioTestCase):
    def test_region_normalization(self):
        self.assertEqual(account_api.api_region("BR"), "br")
        self.assertEqual(account_api.api_region("ME"), "sg")
        self.assertEqual(account_api.api_region("IND"), "ind")

    async def test_guest_token_extraction(self):
        with patch.object(account_api, "api_get", new=AsyncMock(return_value={
            "success": True,
            "guestBasicInfo": {"access_token": "synthetic-token"},
        })):
            self.assertEqual(await account_api.guest_access_token("123", "secret"), "synthetic-token")

    async def test_bad_guest_response_has_no_token(self):
        with patch.object(account_api, "api_get", new=AsyncMock(return_value={"success": False})):
            self.assertIsNone(await account_api.guest_access_token("123", "secret"))

    async def test_access_token_login_uses_validated_game_identity(self):
        from types import SimpleNamespace
        major = SimpleNamespace(
            account_id="123456", url="https://game.example/", token="session-token",
            server_time="123", aes_ak=b"a" * 16, iv_i=b"b" * 16, region="BR",
        )
        login_proto = SimpleNamespace(nickname="Conta teste", functional_addrs=None, informational_addrs=None)
        with patch("Main.version_config", new=AsyncMock(return_value=("OB55", "1.132.3", "https://game.example/"))):
            with patch("Main._public_api_get", new=AsyncMock(return_value={
                "success": True,
                "tokenBasicInfo": {"uid": 123456, "open_id": "synthetic-open-id", "platform": 4},
            })) as token_lookup:
                with patch("Main.get_device_for_account", return_value={}):
                    with patch("Main.build_majorlogin_payload", new=AsyncMock(return_value=b"payload")) as build_payload:
                        with patch("Main.send_majorlogin", new=AsyncMock(return_value=major)):
                            with patch("Main.send_getlogin", new=AsyncMock(return_value=(login_proto, {}))):
                                result = await process_account_credentials(
                                    "123456", "access_token", access_token="synthetic-game-token",
                                )
        self.assertEqual(result["account_id"], "123456")
        self.assertEqual(result["auth_type"], "access_token")
        self.assertEqual(result["access_token"], "synthetic-game-token")
        self.assertEqual(token_lookup.await_args.args[2]["token_type"], "game")
        self.assertEqual(build_payload.await_args.args[0], "synthetic-open-id")


class ImageUrlTests(unittest.TestCase):
    def test_accepts_documented_image_object(self):
        url = "https://hostfreefire-api.squareweb.app/api/iconsff?image=902000011&format=webp"
        self.assertEqual(_public_image_url({"webp": url}), url)

    def test_resolves_relative_image_url(self):
        self.assertEqual(
            _public_image_url("/api/iconsff?image=901000021"),
            "https://hostfreefire-api.squareweb.app/api/iconsff?image=901000021",
        )

    def test_uses_fallback_id_for_unknown_host(self):
        self.assertEqual(
            _public_image_url("https://invalid.example/image.png", 902000011),
            "https://hostfreefire-api.squareweb.app/api/iconsff?image=902000011&format=webp",
        )


class DashboardHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.accounts_file = os.path.join(self.tempdir.name, "accounts.json")
        with patch.object(dashboard_server, "ACCOUNTS_PATH", self.accounts_file):
            with open(self.accounts_file, "w", encoding="utf-8") as stream:
                json.dump([], stream)
        self.path_patch = patch.object(dashboard_server, "ACCOUNTS_PATH", self.accounts_file)
        self.path_patch.start()
        self.state_accounts_patch = patch.dict(dashboard_server.bot_state.accounts, {}, clear=True)
        self.state_accounts_patch.start()
        self.credentials_patch = patch.dict(dashboard_server.bot_state.account_credentials, {}, clear=True)
        self.credentials_patch.start()

    async def asyncTearDown(self):
        self.credentials_patch.stop()
        self.state_accounts_patch.stop()
        self.path_patch.stop()
        self.tempdir.cleanup()

    @staticmethod
    def request(data):
        async def get_json():
            return data
        return SimpleNamespace(json=get_json)

    @staticmethod
    def response_data(response):
        return json.loads(response.text)

    async def test_access_token_is_validated_and_saved(self):
        token = "synthetic-access-token"
        with patch.object(dashboard_server, "ff_api_get", new=AsyncMock(return_value={
            "success": True,
            "tokenBasicInfo": {"uid": 123456, "open_id": "synthetic-open-id", "platform": 4},
        })):
            response = await dashboard_server.handle_add_account(self.request({
                "auth_type": "access_token", "access_token": token,
            }))
        self.assertEqual(self.response_data(response)["status"], "ok")
        with open(self.accounts_file, encoding="utf-8") as stream:
            saved = json.load(stream)
        self.assertEqual(saved[0]["uid"], "123456")
        self.assertEqual(saved[0]["access_token"], token)

    async def test_invalid_token_is_not_saved(self):
        with patch.object(dashboard_server, "ff_api_get", new=AsyncMock(return_value={"success": False})):
            response = await dashboard_server.handle_add_account(self.request({
                "auth_type": "access_token", "access_token": "invalid",
            }))
        self.assertEqual(self.response_data(response)["status"], "error")
        with open(self.accounts_file, encoding="utf-8") as stream:
            self.assertEqual(json.load(stream), [])

    async def test_guest_credentials_are_never_returned_by_stats(self):
        with open(self.accounts_file, "w", encoding="utf-8") as stream:
            json.dump([{"uid": "123", "password": "private-secret", "auth_type": "guest"}], stream)
        dashboard_server.bot_state.accounts["123"] = {"uid": "123", "nickname": "Test"}
        response = await dashboard_server.handle_get_stats(self.request({}))
        serialized = response.text
        self.assertNotIn("private-secret", serialized)

    async def test_guest_nickname_action_exchanges_token_and_sends_change(self):
        with open(self.accounts_file, "w", encoding="utf-8") as stream:
            json.dump([{"uid": "123", "password": "private-secret", "auth_type": "guest"}], stream)
        dashboard_server.bot_state.accounts["123"] = {"uid": "123", "region": "BR"}
        with patch.object(dashboard_server, "guest_access_token", new=AsyncMock(return_value="synthetic-access-token")):
            with patch.object(dashboard_server, "ff_api_get", new=AsyncMock(return_value={
                "success": True, "message": "nickname changed successfully!",
            })) as api_call:
                response = await dashboard_server.handle_account_manage(self.request({
                    "uid": "123", "action": "change_nick", "nickname": "NovoNome",
                }))
        self.assertEqual(self.response_data(response)["status"], "ok")
        self.assertEqual(api_call.await_args.args[0], "change_nick")
        self.assertEqual(api_call.await_args.args[1]["access_token"], "synthetic-access-token")
        self.assertEqual(api_call.await_args.args[1]["nickname"], "NovoNome")
        self.assertNotIn("private-secret", response.text)

    async def test_empty_wishlist_is_a_valid_empty_result(self):
        dashboard_server.bot_state.accounts["456"] = {"uid": "456", "region": "BR"}
        with open(self.accounts_file, "w", encoding="utf-8") as stream:
            json.dump([{"uid": "456", "password": "private-secret", "auth_type": "guest"}], stream)
        with patch.object(dashboard_server, "ff_api_get", new=AsyncMock(return_value={
            "success": False, "error": "no items found in this player's wishlist",
        })):
            response = await dashboard_server.handle_account_manage(self.request({
                "uid": "456", "action": "wishlist",
            }))
        self.assertEqual(self.response_data(response)["status"], "ok")

    async def test_airdrop_query_uses_documented_guest_parameter_names(self):
        dashboard_server.bot_state.accounts["456"] = {"uid": "456", "region": "BR"}
        with open(self.accounts_file, "w", encoding="utf-8") as stream:
            json.dump([{"uid": "456", "password": "private-secret", "auth_type": "guest"}], stream)
        with patch.object(dashboard_server, "ff_api_get", new=AsyncMock(return_value={
            "status": "success", "AirDropInfo": {"diamond-airdrop": True, "airdrop-id": 640},
        })) as api_call:
            response = await dashboard_server.handle_account_manage(self.request({
                "uid": "456", "action": "check_airdrop",
            }))
        self.assertEqual(self.response_data(response)["status"], "ok")
        self.assertEqual(api_call.await_args.args[0], "guest/check_airdrop")
        self.assertEqual(api_call.await_args.args[1]["uid"], "456")
        self.assertEqual(api_call.await_args.args[1]["pass"], "private-secret")

    async def test_wallet_invalid_token_is_reported_as_error(self):
        dashboard_server.bot_state.accounts["789"] = {"uid": "789", "region": "BR"}
        with open(self.accounts_file, "w", encoding="utf-8") as stream:
            json.dump([{"uid": "789", "access_token": "bad-token", "auth_type": "access_token"}], stream)
        with patch.object(dashboard_server, "ff_api_get", new=AsyncMock(return_value={
            "status": "INVALID_TOKEN", "message": "AccessToken Invalid.",
        })):
            response = await dashboard_server.handle_account_manage(self.request({
                "uid": "789", "action": "diamonds",
            }))
        self.assertEqual(self.response_data(response)["status"], "error")


if __name__ == "__main__":
    unittest.main()
