# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web
from account_api import api_get as ff_api_get, api_region as ff_api_region, guest_access_token

# Global bot state shared between Main.py and Web Dashboard
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, str] = {}
        self.squad_status: Dict[str, Any] = {
            "status": "IDLE", "members": [], "leader_uid": None,
            "accepted": [], "mode": "BR", "message": "",
        }

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": uid
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": level or 1,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "likes": likes or 0,
                "status": "ONLINE",
                "profile_initialized": True,
                "ban_status": "PENDENTE",
                "ban_reason": None,
                "api_profile_status": "PENDENTE",
                "api_last_checked": None,
                "ban_checked_at": None,
                "ban_period": None,
                "exp_source": "sessão do jogo",
                "exp_check_status": "PENDENTE",
                "exp_last_check": None,
                "avatar_url": None,
                "banner_url": None,
                "outfit_url": None,
                "skins": [],
                "career_br_matches": 0,
                "career_br_wins": 0,
                "career_br_kills": 0,
                "career_cs_matches": 0,
                "career_cs_wins": 0,
                "career_api_status": "PENDENTE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S")
            }
        else:
            acc = self.accounts[uid_str]
            defaults = {
                "profile_initialized": True, "ban_status": "PENDENTE", "ban_reason": None,
                "api_profile_status": "PENDENTE", "api_last_checked": None,
                "ban_checked_at": None, "ban_period": None,
                "exp_source": "sessão do jogo", "exp_check_status": "PENDENTE", "exp_last_check": None,
                "avatar_url": None, "banner_url": None, "outfit_url": None, "skins": [],
                "career_br_matches": 0, "career_br_wins": 0, "career_br_kills": 0,
                "career_cs_matches": 0, "career_cs_wins": 0, "career_api_status": "PENDENTE"
            }
            for key, value in defaults.items():
                acc.setdefault(key, value)
            if not acc.get("profile_initialized", True):
                acc["initial_exp"] = exp
                acc["profile_initialized"] = True
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["likes"] = likes
            acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff > 0:
                self.log(f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! Total Gained: +{acc['gained_exp']}", "success", uid_str)
            self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"Account {self.accounts[uid_str]['nickname']} finished Match #{self.accounts[uid_str]['matches_played']}", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()


# ==================== HTTP HANDLERS ====================

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")
ACCOUNTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")

async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_br_career_matches": sum(int(a.get("career_br_matches", 0) or 0) for a in bot_state.accounts.values()),
        "total_gained_exp": bot_state.total_gained_exp,
        "accounts": accounts_data,
        "logs": bot_state.logs[-60:],
        "squad": bot_state.squad_status,
        "uptime": int(time.time() - bot_state.start_time)
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        auth_type = str(data.get("auth_type", "guest")).strip().lower()
        existing = []
        if os.path.exists(ACCOUNTS_PATH):
            try:
                with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        callback_data = None
        if auth_type == "guest":
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid.isdigit() or len(uid) > 20 or not pwd or len(pwd) > 512:
                return web.json_response({"status": "error", "error": "Informe um UID numérico válido e uma senha de até 512 caracteres."}, status=400)
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "password": pwd, "auth_type": "guest"})
            callback_data = {"uid": uid, "password": pwd, "auth_type": "guest"}
        elif auth_type == "access_token":
            access_token = str(data.get("access_token", "")).strip()
            if not access_token or len(access_token) > 8192:
                return web.json_response({"status": "error", "error": "Informe um Access Token de jogo válido."}, status=400)
            token_info = await ff_api_get("v1/token", {"access_token": access_token, "token_type": "game"})
            token_basic = token_info.get("tokenBasicInfo") if isinstance(token_info, dict) else None
            uid = str(token_basic.get("uid", "")).strip() if isinstance(token_basic, dict) else ""
            if not uid.isdigit():
                return web.json_response({"status": "error", "error": "Token inválido ou não reconhecido como Access Token de jogo."}, status=400)
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            existing.append({"uid": uid, "auth_type": "access_token", "access_token": access_token})
            callback_data = {"uid": uid, "auth_type": "access_token", "access_token": access_token}
        else:
            return web.json_response({"status": "error", "error": "Tipo de autenticação inválido."}, status=400)

        tmp_path = ACCOUNTS_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp_path, ACCOUNTS_PATH)
        try:
            os.chmod(ACCOUNTS_PATH, 0o600)
        except OSError:
            pass

        bot_state.log(f"Conta adicionada ({auth_type}): {uid}", "success", uid)
        
        # Trigger dynamic worker launch
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](callback_data))

        return web.json_response({"status": "ok", "uid": uid})
    except Exception as e:
        bot_state.log(f"Erro ao adicionar conta ({type(e).__name__}).", "error")
        return web.json_response({"status": "error", "error": "Não foi possível salvar a conta."}, status=500)


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        login_uids = {uid}
        login_uids.update(guest_uid for guest_uid, profile_uid in bot_state.account_credentials.items() if str(profile_uid) == uid)
        if os.path.exists(ACCOUNTS_PATH):
            with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing = [acc for acc in existing if str(acc.get("uid")) not in login_uids]
            with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            try:
                os.chmod(ACCOUNTS_PATH, 0o600)
            except OSError:
                pass

        if uid in bot_state.accounts:
            del bot_state.accounts[uid]

        for login_uid in login_uids:
            if login_uid in bot_state.account_workers:
                bot_state.account_workers[login_uid].cancel()
                del bot_state.account_workers[login_uid]
            bot_state.account_credentials.pop(login_uid, None)

        bot_state.log(f"Account {uid} removed from rotation.", "warning", uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


def _stored_account_auth(uid: str) -> dict[str, Any] | None:
    """Localiza credencial pelo UID visível, incluindo UID de login Guest mapeado."""
    login_uids = {str(uid)}
    login_uids.update(login_uid for login_uid, profile_uid in bot_state.account_credentials.items()
                      if str(profile_uid) == str(uid))
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("uid", "")) in login_uids:
            if entry.get("access_token") or (entry.get("uid") and entry.get("password")):
                return entry
    return None


async def handle_account_manage(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        action = str(data.get("action", "")).strip().lower()
        if not uid.isdigit():
            return web.json_response({"status": "error", "error": "UID inválido."}, status=400)
        account = bot_state.accounts.get(uid)
        if not account:
            return web.json_response({"status": "error", "error": "Conta não encontrada no painel."}, status=404)
        stored = _stored_account_auth(uid)
        if not stored:
            return web.json_response({"status": "error", "error": "Credencial local da conta não encontrada."}, status=404)

        params: dict[str, Any] = {}
        if stored.get("access_token"):
            api_auth = {"access_token": str(stored["access_token"])}
        else:
            api_auth = {"uid": str(stored["uid"]), "password": str(stored["password"])}
        region = ff_api_region(account.get("region", "BR"))

        if action == "friends":
            path = "get_friends"
            params.update(api_auth)
        elif action in {"add_friend", "remove_friend"}:
            friend_id = str(data.get("friend_id", "")).strip()
            if not friend_id.isdigit() or len(friend_id) > 20:
                return web.json_response({"status": "error", "error": "Informe um UID numérico válido para o amigo."}, status=400)
            path = action
            params.update(api_auth, id=friend_id)
        elif action == "wishlist":
            path = "wishlist"
            params.update(id=uid, region=region)
        elif action == "diamonds":
            path = "diamonds"
            params.update(api_auth, region=region)
        elif action in {"check_airdrop", "check_xp_card"}:
            path = "guest/check_airdrop" if action == "check_airdrop" else "check_xp_card"
            if stored.get("access_token"):
                params["access_token"] = str(stored["access_token"])
            else:
                params.update(uid=str(stored["uid"]), **{"pass": str(stored["password"])})
        elif action in {"wishlist_add", "wishlist_remove"}:
            raw_ids = str(data.get("item_ids", "")).strip()
            item_ids = [part.strip() for part in raw_ids.split(",") if part.strip()]
            if not item_ids or len(item_ids) > 30 or any(not item.isdigit() for item in item_ids):
                return web.json_response({"status": "error", "error": "Informe até 30 IDs de itens numéricos, separados por vírgula."}, status=400)
            path = action
            params.update(api_auth, item_id=",".join(item_ids), region=region)
        elif action in {"change_nick", "bio_change"}:
            token = str(stored.get("access_token", ""))
            if not token:
                token = await guest_access_token(str(stored["uid"]), str(stored["password"])) or ""
            if not token:
                return web.json_response({"status": "error", "error": "Não foi possível obter um token para esta conta Guest."}, status=502)
            params["access_token"] = token
            if action == "change_nick":
                nickname = str(data.get("nickname", "")).strip()
                if not nickname or len(nickname) > 30:
                    return web.json_response({"status": "error", "error": "Informe um nickname de até 30 caracteres."}, status=400)
                path = "change_nick"
                params["nickname"] = nickname
            else:
                bio = str(data.get("bio", "")).strip()
                if not bio or len(bio) > 500:
                    return web.json_response({"status": "error", "error": "Informe uma bio de até 500 caracteres."}, status=400)
                path = "bio_change"
                params.update(new_bio=bio, region=region)
        else:
            return web.json_response({"status": "error", "error": "Ação não suportada."}, status=400)

        result = await ff_api_get(path, params)
        if not isinstance(result, dict):
            return web.json_response({"status": "error", "error": "A API não respondeu. Tente novamente mais tarde."}, status=502)
        success_value = result.get("success")
        failed = success_value is False or str(success_value).strip().lower() == "false"
        empty_wishlist = action == "wishlist" and "no items found" in str(result.get("error", "")).lower()
        api_status = str(result.get("status", "")).strip().lower()
        failed = failed or api_status in {"error", "erro", "invalid_token", "invalid_guest", "failed"} or bool(result.get("error"))
        api_error = (result.get("error") or result.get("message")) if failed and not empty_wishlist else None
        if api_error:
            return web.json_response({"status": "error", "error": str(api_error), "data": result}, status=400)
        bot_state.log(f"Ação da API concluída: {action}", "success", uid)
        return web.json_response({"status": "ok", "data": result})
    except Exception as e:
        bot_state.log(f"Falha em operação da API ({type(e).__name__}).", "error")
        return web.json_response({"status": "error", "error": "Falha ao executar a ação da conta."}, status=500)


async def handle_squad_start(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        members = data.get("members")
        mode = str(data.get("mode", "CS")).upper()
        if not isinstance(members, list) or len(members) != 4:
            return web.json_response({"status": "error", "error": "Selecione exatamente quatro contas para iniciar a squad."}, status=400)
        members = [str(uid).strip() for uid in members]
        if any(not uid.isdigit() or len(uid) > 20 for uid in members) or len(set(members)) != 4:
            return web.json_response({"status": "error", "error": "As quatro vagas precisam conter UIDs numéricos distintos."}, status=400)
        if mode not in {"BR", "CS"}:
            return web.json_response({"status": "error", "error": "Modo inválido; use BR ou CS."}, status=400)
        callback = bot_state.refresh_callbacks.get("on_squad_start")
        if not callback:
            return web.json_response({"status": "error", "error": "O controle de squad não foi inicializado pela Main."}, status=503)
        result = await callback(members, mode)
        if not isinstance(result, dict) or result.get("status") != "ok":
            message = result.get("error", "Não foi possível preparar a squad.") if isinstance(result, dict) else "Não foi possível preparar a squad."
            return web.json_response({"status": "error", "error": message}, status=409)
        return web.json_response(result)
    except Exception as e:
        bot_state.log(f"Erro ao iniciar squad: {e}", "error")
        return web.json_response({"status": "error", "error": "Falha ao preparar a squad."}, status=500)


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/manage", handle_account_manage)
    app.router.add_post("/api/squad/start", handle_squad_start)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on http://localhost:{port}\033[0m")
