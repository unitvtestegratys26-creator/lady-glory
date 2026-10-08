# -*- coding: utf-8 -*-
import sys
import os
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ.setdefault('PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION', 'python')
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import asyncio
import httpx
import random
import json
import socket
import struct
import time
import uuid
import itertools
from urllib.parse import urlparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from google_play_scraper import app as play_scraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser
from message_ids import MESSAGE_ID_TO_NAME
import thunderFF_pb2
from dashboard_server import ACCOUNTS_PATH, bot_state, start_web_dashboard
from squad_protocol import build_accept_invite, build_create_squad, build_invite, build_status_request
from gateway_framing import read_gateway_frame

MAX_MATCH_DURATION = 1500
MATCH_IDLE_TIMEOUT = 2
NON_MATCH_RECONNECT_DELAY = 0.5

MODE_ID = 1
MAP_ID = 1
CS_MODE_ID = 6
CS_MAP_ID = 15
EXTRA_SQUAD_INVITE_UID = "168274223"
SQUAD_PROTOCOL_REGION = "BR"

xK, xV = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
AES_KEY = xK
AES_IV = xV

CRC7_TABLE = bytes([
    0, 9, 18, 27, 36, 45, 54, 63, 72, 65, 90, 83, 108, 101, 126, 119,
    25, 16, 11, 2, 61, 52, 47, 38, 81, 88, 67, 74, 117, 124, 103, 110,
    50, 59, 32, 41, 22, 31, 4, 13, 122, 115, 104, 97, 94, 87, 76, 69,
    43, 34, 57, 48, 15, 6, 29, 20, 99, 106, 113, 120, 71, 78, 85, 92,
    100, 109, 118, 127, 64, 73, 82, 91, 44, 37, 62, 55, 8, 1, 26, 19,
    125, 116, 111, 102, 89, 80, 75, 66, 53, 60, 39, 46, 17, 24, 3, 10,
    86, 95, 68, 77, 114, 123, 96, 105, 30, 23, 12, 5, 58, 51, 40, 33,
    79, 70, 93, 84, 107, 98, 121, 112, 7, 14, 21, 28, 35, 42, 49, 56,
    65, 72, 83, 90, 101, 108, 119, 126, 9, 0, 27, 18, 45, 36, 63, 54,
    88, 81, 74, 67, 124, 117, 110, 103, 16, 25, 2, 11, 52, 61, 38, 47,
    115, 122, 97, 104, 87, 94, 69, 76, 59, 50, 41, 32, 31, 22, 13, 4,
    106, 99, 120, 113, 78, 71, 92, 85, 34, 43, 48, 57, 6, 15, 20, 29,
    37, 44, 55, 62, 1, 8, 19, 26, 109, 100, 127, 118, 73, 64, 91, 82,
    60, 53, 46, 39, 24, 17, 10, 3, 116, 125, 102, 111, 80, 89, 66, 75,
    23, 30, 5, 12, 51, 58, 33, 40, 95, 86, 77, 68, 123, 114, 105, 96,
    14, 7, 28, 21, 42, 35, 56, 49, 70, 79, 84, 93, 98, 107, 112, 121,
])

_DELTA = 0x9E3779B9
_ROUNDS = 16
_FIELD_SIZES = {0: 1, 1: 2, 2: 2, 3: 1, 4: 2}
_FIELD_NAMES = {0: "sendOption", 1: "cmd", 2: "orderId", 3: "flags", 4: "length"}

CLOUDFLARE_PRIMARY_DNS = "1.1.1.1"
CLOUDFLARE_SECONDARY_DNS = "1.0.0.1"
_DNS_CACHE: Dict[str, Tuple[str, float]] = {}
_DNS_CACHE_TTL = 300.0

client = httpx.AsyncClient(
    verify=False,
    timeout=15.0,
    limits=httpx.Limits(max_connections=300, max_keepalive_connections=150)
)
_LOGIN_SEMAPHORE = asyncio.Semaphore(4)

headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': 'OB55'
}


def log(msg):
    text = str(msg)
    print(text, flush=True)
    lowered = text.lower()
    if text.startswith("[-]") or "error" in lowered or "failed" in lowered:
        level = "error"
    elif text.startswith("[!]") or "warning" in lowered:
        level = "warning"
    elif text.startswith("[+]") or "login ok" in lowered or "send-ok" in lowered:
        level = "success"
    else:
        level = "info"
    bot_state.log(text[:600], level)
def print_error(msg): log(f"[-] {msg}")
def print_success(msg): log(f"[+] {msg}")
def print_info(msg): log(f"[i] {msg}")
def print_warning(msg): log(f"[!] {msg}")


class SquadCoordinator:
    """Coordinates one explicitly requested BR/CS squad match for four accounts."""
    ACTIVE_STATES = {"PREPARING", "CREATING_SQUAD", "VERIFYING_LEADER", "INVITING", "WAITING_FOR_ACCEPTANCE", "VERIFYING_MEMBERS", "READY", "QUEUEING", "IN_MATCH"}

    def __init__(self):
        self.members: List[str] = []
        self.mode = "CS"
        self.status = "IDLE"
        self.message = ""
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.chat_sessions: Dict[str, Dict[str, Any]] = {}
        self.accepted = set()
        self.pending_accepts = set()
        self.server_status: Dict[str, Dict[str, Any]] = {}
        self.status_event = asyncio.Event()
        self.leader_confirmed = False
        self.server_member_count = 0
        self.server_capacity = 4
        self.background_tasks = set()
        self.invites_sent = False
        self.queue_started = False
        self.finished = set()
        self.restart_event = asyncio.Event()
        self.lock = asyncio.Lock()

    def _publish(self):
        message = self.message
        if self.status == "PREPARING":
            message = f"Sessões no lobby: {len(self.sessions)}/4. {message}"
        confirmed = max(
            len(self.accepted) + (1 if self.leader_confirmed else 0),
            self.server_member_count,
        )
        bot_state.squad_status = {
            "status": self.status,
            "members": list(self.members),
            "leader_uid": self.members[0] if self.members else None,
            "accepted": sorted(self.accepted),
            "accepted_count": len(self.accepted),
            "confirmed_count": min(4, confirmed),
            "server_member_count": self.server_member_count,
            "server_capacity": self.server_capacity or 4,
            "invitee_confirmed_count": max(len(self.accepted), max(0, self.server_member_count - 1)),
            "invitee_target_count": 3,
            "connected_count": len(self.sessions),
            "mode": self.mode,
            "message": message,
        }

    async def activate(self, members: List[str], mode: str = "CS"):
        mode = str(mode or "CS").upper()
        if mode not in {"BR", "CS"}:
            return {"status": "error", "error": "Modo inválido; use BR ou CS."}
        async with self.lock:
            if self.status in self.ACTIVE_STATES:
                return {"status": "error", "error": "Já existe uma squad em preparação ou em partida."}
            old_restart = self.restart_event
            old_tasks = list(self.background_tasks)
            self.background_tasks.clear()
            self.members = list(members)
            self.mode = mode
            self.status = "PREPARING"
            self.message = "Aguardando as quatro sessões no lobby. A busca individual está desativada."
            self.sessions = {}
            self.accepted = set()
            self.pending_accepts = set()
            self.server_status = {}
            self.leader_confirmed = False
            self.server_member_count = 0
            self.server_capacity = 4
            self.status_event = asyncio.Event()
            self.invites_sent = False
            self.queue_started = False
            self.finished = set()
            self.restart_event = asyncio.Event()
            self._publish()
            old_restart.set()
            available_sessions = {
                uid: session for uid, session in live_gateway_sessions.items()
                if uid in self.members and not session["writer"].is_closing()
            }
            self.chat_sessions = {
                uid: session for uid, session in live_chat_sessions.items()
                if uid in self.members and not session["writer"].is_closing()
            }
        for task in old_tasks:
            task.cancel()
        # Sessions are already connected to the lobby because automatic solo
        # matchmaking is disabled. Re-register them so the leader can create
        # the squad without waiting for a reconnect.
        for uid in self.members:
            if uid in available_sessions:
                await self.register_session(uid, available_sessions[uid])
        return {"status": "ok", "message": self.message}

    def is_member(self, uid: str) -> bool:
        return str(uid) in self.members

    def is_active_member(self, uid: str) -> bool:
        return self.is_member(uid) and self.status in self.ACTIVE_STATES

    def should_hold(self, uid: str) -> bool:
        return self.is_member(uid) and self.status in {"FINISHED", "ERROR"}

    def is_registered(self, uid: str, writer) -> bool:
        session = self.sessions.get(str(uid))
        return bool(session and session.get("writer") is writer)

    def should_migrate(self, uid: str, writer) -> bool:
        if not self.is_member(uid):
            return False
        if self.status in {"FINISHED", "ERROR"}:
            return True
        return self.status in self.ACTIVE_STATES and not self.is_registered(uid, writer)

    async def wait_if_held(self, uid: str):
        while self.should_hold(uid):
            event = self.restart_event
            await event.wait()

    async def register_session(self, uid: str, session: Dict[str, Any]):
        uid = str(uid)
        async with self.lock:
            if not self.is_active_member(uid):
                return
            self.sessions[uid] = session
            ready_sessions = sum(1 for member in self.members if member in self.sessions)
            if ready_sessions == 4 and not self.invites_sent:
                self.message = f"Quatro sessões de jogo prontas; preparando a squad {self.mode}."
            self._publish()
        bot_state.log(f"Sessão da vaga {uid} registrada para a squad: {ready_sessions}/4 conectadas.", "info", uid)
        await self._maybe_launch_creation()

    async def register_chat_session(self, uid: str, session: Dict[str, Any]):
        uid = str(uid)
        async with self.lock:
            if not self.is_active_member(uid):
                return
            self.chat_sessions[uid] = session
            self._publish()
        if self.members and uid == self.members[0]:
            bot_state.log("Canal informacional conectado; não será usado para autenticar nem enviar convites da squad.", "info", uid)
        await self._maybe_launch_creation()

    async def unregister_chat_session(self, uid: str, writer):
        uid = str(uid)
        async with self.lock:
            session = self.chat_sessions.get(uid)
            if session and session.get("writer") is writer:
                self.chat_sessions.pop(uid, None)
                self._publish()

    async def _maybe_launch_creation(self):
        launch = False
        async with self.lock:
            if not self.members or self.status not in self.ACTIVE_STATES:
                return
            ready_sessions = sum(1 for member in self.members if member in self.sessions)
            if ready_sessions == 4 and not self.invites_sent:
                self.invites_sent = True
                self.status = "CREATING_SQUAD"
                self.message = f"Quatro sessões de jogo prontas; criando a squad {self.mode} sem usar o canal ChaT."
                launch = True
            self._publish()
        if launch:
            bot_state.log(f"Quatro sessões de jogo conectadas; iniciando criação da squad {self.mode} sem AutH_Chat.", "info", self.members[0])
            task = asyncio.create_task(self._create_and_invite())
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

    async def _create_and_invite(self):
        leader_uid = self.members[0]
        leader_session = self.sessions.get(leader_uid)
        try:
            if not leader_session or leader_session["writer"].is_closing():
                raise ConnectionError("A sessão TCP da vaga 1 não está disponível")
            writer = leader_session["writer"]
            bot_state.log(
                f"Enviando criação da squad {self.mode} pela vaga 1 ({leader_uid}); "
                f"região de protocolo={SQUAD_PROTOCOL_REGION}.",
                "info", leader_uid
            )
            writer.write(build_create_squad(
                self.mode,
                leader_session["key"], leader_session["iv"],
                SQUAD_PROTOCOL_REGION, leader_session.get("client_version", "")
            ))
            await writer.drain()
            bot_state.log(f"Pedido de criação {self.mode} escrito na conexão da vaga 1; aguardando status INSQUAD.", "info", leader_uid)
            async with self.lock:
                self.status = "VERIFYING_LEADER"
                self.message = f"Pedido de criação {self.mode} enviado. Aguardando o servidor confirmar que a vaga 1 virou líder da squad."
                self._publish()
            if not await self._wait_for_membership(leader_uid, leader_uid):
                raise TimeoutError("o servidor não confirmou a vaga 1 em INSQUAD como líder")

            bot_state.log(f"Servidor confirmou a vaga 1 como líder da squad {self.mode}.", "success", leader_uid)
            bot_state.log("AutH_Chat e mensagens de chat desativados; convites serão enviados pelo gateway.", "info", leader_uid)
            await asyncio.sleep(0.5)
            async with self.lock:
                self.status = "INVITING"
                self.message = f"Líder confirmado; enviando convite às três Guests e ao UID de teste {EXTRA_SQUAD_INVITE_UID}."
                self._publish()
                invite_targets = list(dict.fromkeys([EXTRA_SQUAD_INVITE_UID, *self.members[1:]]))
            invite_region = SQUAD_PROTOCOL_REGION
            for target_uid in invite_targets:
                invite_packet = build_invite(
                    target_uid, leader_session["key"], leader_session["iv"], invite_region
                )
                bot_state.log(
                    f"Enviando convite para UID {target_uid}: lobby={self.mode}, região={invite_region}, "
                    f"packet_id={invite_packet[:2].hex().upper()}, bytes={len(invite_packet)}.",
                    "info", leader_uid
                )
                writer.write(invite_packet)
                await writer.drain()
                bot_state.log(
                    f"Convite {invite_packet[:2].hex().upper()} para {target_uid} escrito no gateway; "
                    "isso não confirma recebimento pelo servidor nem aceite.",
                    "info", leader_uid
                )
                # Space invitation requests to avoid sending a burst to the lobby service.
                await asyncio.sleep(1.0)
            async with self.lock:
                if self.status == "INVITING":
                    self.status = "WAITING_FOR_ACCEPTANCE"
                self.message = "Quatro convites enviados (três Guests + UID de teste); aguardando confirmação de três convidados na squad."
                self._publish()
            timeout_task = asyncio.create_task(self._monitor_invitee_count(90.0))
            self.background_tasks.add(timeout_task)
            timeout_task.add_done_callback(self.background_tasks.discard)
            bot_state.log(
                f"Squad {self.mode}: convites escritos para três Guests e UID {EXTRA_SQUAD_INVITE_UID}; "
                "a busca só começa após três participantes confirmados.", "info", leader_uid
            )
        except Exception as exc:
            await self._fail(f"Não foi possível confirmar/criar a squad: {exc}")

    def _confirmed_invitee_count(self) -> int:
        return max(len(self.accepted), max(0, self.server_member_count - 1))

    async def _monitor_invitee_count(self, timeout: float):
        leader_uid = self.members[0]
        leader = self.sessions.get(leader_uid)
        if not leader:
            await self._fail("Sessão do líder ausente ao monitorar a squad CS; busca bloqueada.")
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.status not in {"INVITING", "WAITING_FOR_ACCEPTANCE", "VERIFYING_MEMBERS"}:
                return
            if self._confirmed_invitee_count() >= 3:
                return
            try:
                leader["writer"].write(build_status_request(leader_uid, leader["key"], leader["iv"]))
                await asyncio.wait_for(leader["writer"].drain(), timeout=3)
            except Exception as exc:
                await self._fail(f"Falha ao consultar vagas da squad: {exc}")
                return
            await asyncio.sleep(1.5)
        if self.status in {"INVITING", "WAITING_FOR_ACCEPTANCE", "VERIFYING_MEMBERS"} and self._confirmed_invitee_count() < 3:
            await self._fail(
                f"Tempo esgotado: o servidor confirmou {self._confirmed_invitee_count()}/3 convidados. "
                "A busca não foi iniciada."
            )

    async def _wait_for_membership(self, uid: str, expected_leader: str, timeout: float = 16.0) -> bool:
        session = self.sessions.get(str(uid))
        if not session or session["writer"].is_closing():
            return False
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            self.status_event.clear()
            requested_at = asyncio.get_running_loop().time()
            try:
                session["writer"].write(build_status_request(uid, session["key"], session["iv"]))
                await asyncio.wait_for(session["writer"].drain(), timeout=3)
            except Exception as exc:
                bot_state.log(f"Falha ao consultar status INSQUAD de {uid}: {exc}", "warning", uid)
                return False
            remaining = max(0.05, min(1.5, deadline - asyncio.get_running_loop().time()))
            try:
                await asyncio.wait_for(self.status_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass
            info = self.server_status.get(str(uid))
            if info and info.get("received_at", 0) >= requested_at:
                if info.get("status_code") == 2 and str(info.get("leader_uid")) == str(expected_leader):
                    return True
            await asyncio.sleep(0.15)
        return False

    async def _fail(self, message: str):
        async with self.lock:
            self.status = "ERROR"
            self.message = message
            self._publish()
        bot_state.log(message, "error")

    async def handle_server_status(self, uid: str, status_code: int, leader_uid: Any,
                                   member_count: Any = None, member_capacity: Any = 4):
        uid = str(uid)
        if not self.is_active_member(uid):
            return
        try:
            owner = str(int(leader_uid)) if leader_uid is not None else None
        except (TypeError, ValueError):
            owner = str(leader_uid) if leader_uid is not None else None
        self.server_status[uid] = {
            "status_code": int(status_code),
            "leader_uid": owner,
            "member_count": member_count,
            "member_capacity": member_capacity,
            "received_at": asyncio.get_running_loop().time(),
        }
        self.status_event.set()
        if int(status_code) != 2 or owner != self.members[0]:
            return

        try:
            observed_count = int(member_count)
            if observed_count > 0:
                self.server_member_count = max(self.server_member_count, observed_count)
        except (TypeError, ValueError):
            pass
        try:
            observed_capacity = int(member_capacity)
            if observed_capacity > 0:
                self.server_capacity = max(4, observed_capacity)
        except (TypeError, ValueError):
            self.server_capacity = 4

        queue_ready = False
        async with self.lock:
            if uid == self.members[0]:
                self.leader_confirmed = True
            else:
                self.accepted.add(uid)
                self.pending_accepts.discard(uid)
            if self.leader_confirmed and self._confirmed_invitee_count() >= 3:
                self.status = "READY"
                self.message = f"Servidor confirmou {min(4, self.server_member_count)}/4 na squad {self.mode}; três convidados confirmados, iniciando uma única busca pelo líder."
                queue_ready = True
            elif uid != self.members[0]:
                self.status = "VERIFYING_MEMBERS"
                self.message = f"Servidor confirmou {min(4, max(1 + len(self.accepted), self.server_member_count))}/4 na squad {self.mode}; aguardando três convidados."
            self._publish()
        bot_state.log(
            f"Status do servidor para UID {uid}: INSQUAD, líder {owner}, squad {min(4, self.server_member_count)}/4.",
            "success", uid
        )
        if queue_ready:
            await self.start_queue_once()

    async def accept_group_invite(self, uid: str, inviter_uid: str, target_uid: str, invite_code: Any, session: Dict[str, Any]) -> bool:
        uid, inviter_uid, target_uid = str(uid), str(inviter_uid), str(target_uid)
        if not self.is_active_member(uid):
            return False
        if uid == self.members[0]:
            bot_state.log(f"Convite 0500 ignorado para UID {uid}: a vaga 1 é o líder, não um convidado.", "warning", uid)
            return False
        if inviter_uid != self.members[0]:
            bot_state.log(
                f"Convite 0500 recusado para UID {uid}: remetente {inviter_uid} não é o líder selecionado {self.members[0]}.",
                "warning", uid
            )
            return False
        if target_uid != uid or uid not in self.members[1:]:
            bot_state.log(
                f"Convite 0500 recusado: UID alvo {target_uid} não corresponde ao convidado selecionado {uid}.",
                "warning", uid
            )
            return False
        if invite_code is None or str(invite_code) in {"", "None"}:
            bot_state.log(f"Convite 0500 recusado para UID {uid}: código do convite ausente.", "warning", uid)
            return False
        async with self.lock:
            if uid in self.accepted or uid in self.pending_accepts:
                bot_state.log(f"Convite 0500 duplicado ignorado para UID {uid}.", "warning", uid)
                return False
            if self.status not in {"INVITING", "WAITING_FOR_ACCEPTANCE", "VERIFYING_MEMBERS"}:
                bot_state.log(
                    f"Convite 0500 recusado para UID {uid}: squad está no estado {self.status}, não aguardando convites.",
                    "warning", uid
                )
                return False
            self.pending_accepts.add(uid)
        try:
            writer = session["writer"]
            writer.write(build_accept_invite(
                inviter_uid, invite_code, session["key"], session["iv"],
                SQUAD_PROTOCOL_REGION, session.get("client_version", "")
            ))
            await writer.drain()
            async with self.lock:
                self.status = "VERIFYING_MEMBERS"
                self.message = f"Aceite enviado por {uid}; aguardando o servidor confirmar que entrou na squad do líder."
                self._publish()
            bot_state.log(f"Guest {uid} enviou o aceite; verificando presença na mesma squad.", "info", uid)
            task = asyncio.create_task(self._verify_member(uid))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
            return True
        except Exception as exc:
            async with self.lock:
                self.pending_accepts.discard(uid)
                self.status = "ERROR"
                self.message = "Falha ao aceitar convite; a fila permanece bloqueada."
                self._publish()
            bot_state.log(f"Falha ao aceitar convite da squad para {uid}: {exc}", "error", uid)
            return False

    async def _verify_member(self, uid: str):
        if await self._wait_for_membership(uid, self.members[0]):
            return
        if uid not in self.accepted and self._confirmed_invitee_count() < 3 and self.status not in {"READY", "QUEUEING", "IN_MATCH"}:
            await self._fail(
                f"O servidor não confirmou o UID {uid} na squad do líder. Busca bloqueada para evitar partida solo."
            )

    async def start_queue_once(self):
        async with self.lock:
            if self.status != "READY" or self.queue_started:
                return
            leader = self.sessions.get(self.members[0])
            if not leader or leader["writer"].is_closing():
                self.status = "ERROR"
                self.message = "Líder desconectado antes de iniciar a busca; fila não iniciada."
                self._publish()
                return
            self.queue_started = True
            self.status = "QUEUEING"
            self.message = f"Servidor confirmou três convidados na squad {self.mode}; enviando uma única busca pelo líder."
            self._publish()
        try:
            await start_game_match_search(
                self.mode,
                str(leader.get("region") or "BR").upper(),
                leader.get("client_version", ""),
                leader["writer"], leader["key"], leader["iv"]
            )
            bot_state.log(f"Três convidados confirmados: busca {self.mode} iniciada uma única vez pelo líder.", "success", self.members[0])
        except Exception as exc:
            async with self.lock:
                self.status = "ERROR"
                self.message = f"Falha ao enviar a busca {self.mode}; nenhuma repetição automática será feita."
                self._publish()
            bot_state.log(f"Falha ao iniciar busca da squad: {exc}", "error", self.members[0])

    async def mark_match_found(self, uid: str):
        async with self.lock:
            if self.is_member(uid) and self.status in {"QUEUEING", "READY"}:
                self.status = "IN_MATCH"
                self.message = f"Partida {self.mode} encontrada para a squad."
                self._publish()

    async def mark_match_finished(self, uid: str):
        async with self.lock:
            if not self.is_member(uid) or self.status not in {"IN_MATCH", "QUEUEING"}:
                return
            self.finished.add(str(uid))
            if set(self.members).issubset(self.finished):
                self.status = "FINISHED"
                self.message = "Partida da squad concluída; nenhuma nova fila automática será iniciada."
                self._publish()


squad_coordinator = SquadCoordinator()
live_gateway_sessions: Dict[str, Dict[str, Any]] = {}
live_chat_sessions: Dict[str, Dict[str, Any]] = {}


def _nested_proto_value(root: Any, *path: int):
    node = root
    for field_no in path:
        if not isinstance(node, dict):
            return None
        node = node.get(str(field_no), node.get(field_no))
        if not isinstance(node, dict) or "data" not in node:
            return None
        node = node["data"]
    return node


async def _parse_player_status_response(packet_hex: str):
    """Parse the OB54 0F00 status response; ignore malformed/non-player packets."""
    if not packet_hex.startswith("0f00"):
        return None
    # The response has a six-byte transport header. The status protobuf starts
    # with field 1 (08); try candidate boundaries and validate the known shape.
    for offset in range(8, min(len(packet_hex) - 2, 64), 2):
        if packet_hex[offset:offset + 2] != "08":
            continue
        try:
            parsed = json.loads(await decode_protobuf(packet_hex[offset:]))
            if _nested_proto_value(parsed, 2) != 15:
                continue
            player_uid = _nested_proto_value(parsed, 5, 1, 1)
            status_code = _nested_proto_value(parsed, 5, 1, 3)
            leader_uid = _nested_proto_value(parsed, 5, 1, 8)
            member_count = _nested_proto_value(parsed, 5, 1, 9)
            raw_capacity = _nested_proto_value(parsed, 5, 1, 10)
            try:
                member_capacity = int(raw_capacity) + 1 if raw_capacity is not None else 4
            except (TypeError, ValueError):
                member_capacity = 4
            if member_capacity < 4:
                member_capacity = 4
            if player_uid is None or status_code not in {1, 2, 3, 4, 5, 6, 7}:
                continue
            return {
                "uid": str(player_uid),
                "status_code": int(status_code),
                "leader_uid": leader_uid,
                "member_count": member_count,
                "member_capacity": member_capacity,
            }
        except Exception:
            continue
    return None


def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict):
        return default
    if key in d:
        val = d[key].get('data')
        return val if val is not None else default
    if str(key) in d:
        val = d[str(key)].get('data')
        return val if val is not None else default
    return default


def _pb_varint(n):
    if n < 0:
        n = (1 << 64) + n
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)


def _pb_tag(f, w):
    return _pb_varint((f << 3) | w)


def _pb_field(f, v):
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return _pb_tag(f, 0) + _pb_varint(v)
    if isinstance(v, str):
        d = v.encode('utf-8')
        return _pb_tag(f, 2) + _pb_varint(len(d)) + d
    if isinstance(v, (bytes, bytearray)):
        d = bytes(v)
        return _pb_tag(f, 2) + _pb_varint(len(d)) + d
    return b""


def crc7(data):
    c = 0
    for b in data:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F


def zigzag_encode(n):
    z = n << 1
    out = bytearray()
    while z >= 0x80:
        out.append((z & 0x7F) | 0x80)
        z >>= 7
    out.append(z)
    return bytes(out)


def uleb_encode(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)


def _generate_new_device() -> dict:
    device_list = [
        ("Samsung", "SM-G998B", "Adreno (TM) 660", "Android OS 12 / API-31"),
        ("Xiaomi", "2201122G", "Adreno (TM) 730", "Android OS 13 / API-33"),
        ("Realme", "RMX3700", "Mali-G710", "Android OS 14 / API-34"),
        ("OnePlus", "CPH2451", "Adreno (TM) 740", "Android OS 13 / API-33"),
        ("OPPO", "CPH2611", "Adreno (TM) 720", "Android OS 14 / API-34"),
        ("Vivo", "V2203", "Mali-G710", "Android OS 12 / API-31"),
        ("Poco", "M2102J20SG", "Adreno (TM) 660", "Android OS 13 / API-33"),
    ]
    brand, model, gpu, os_ver = random.choice(device_list)
    return {
        "unique_device_id": f"Google|{str(uuid.uuid4())}",
        "brand": brand, "model": model, "gpu_renderer": gpu, "system_software": os_ver,
        "screen_width": random.choice([1080, 1440, 720, 1280]),
        "screen_height": random.choice([2400, 3200, 1600, 2400]),
        "screen_dpi": str(random.randint(300, 420)),
        "memory": random.randint(2800, 6500),
        "processor_details": f"ARM64 FP ASIMD AES VMH | {random.randint(2200, 3200)} | {random.randint(6, 12)}",
        "client_ip": f"{random.randint(103, 223)}.{random.randint(10, 250)}.{random.randint(10, 250)}.{random.randint(10, 250)}"
    }


def get_device_for_account(account_identifier: str) -> dict:
    return _generate_new_device()


async def resolve_host_cloudflare(hostname: str) -> str:
    if not hostname:
        return hostname
    parts = hostname.split('.')
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return hostname
    now = time.time()
    if hostname in _DNS_CACHE:
        ip, exp = _DNS_CACHE[hostname]
        if now < exp:
            return ip

    def _query_cloudflare(server_ip: str) -> Optional[str]:
        s = None
        try:
            tx_id = random.randint(1000, 65535)
            header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
            qname = b"".join(bytes([len(part)]) + part.encode('ascii') for part in hostname.split('.')) + b"\x00"
            query_pkt = header + qname + struct.pack(">HH", 1, 1)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.2)
            s.sendto(query_pkt, (server_ip, 53))
            resp, _ = s.recvfrom(1024)
            if len(resp) >= 12:
                ancount = struct.unpack(">H", resp[6:8])[0]
                if ancount > 0:
                    offset = 12 + len(qname) + 4
                    for _ in range(ancount):
                        if offset >= len(resp):
                            break
                        if (resp[offset] & 0xC0) == 0xC0:
                            offset += 2
                        else:
                            while offset < len(resp) and resp[offset] != 0:
                                offset += 1 + resp[offset]
                            offset += 1
                        if offset + 10 > len(resp):
                            break
                        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", resp[offset:offset+10])
                        offset += 10
                        if rtype == 1 and rdlen == 4 and offset + 4 <= len(resp):
                            return socket.inet_ntoa(resp[offset:offset+4])
                        offset += rdlen
        except Exception:
            pass
        finally:
            if s:
                try: s.close()
                except Exception: pass
        return None

    loop = asyncio.get_running_loop()
    ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_PRIMARY_DNS)
    if not ip:
        ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_SECONDARY_DNS)
    if not ip:
        try:
            ip_info = await loop.getaddrinfo(hostname, None, family=socket.AF_INET)
            if ip_info:
                ip = ip_info[0][4][0]
        except Exception:
            ip = hostname
    if ip:
        _DNS_CACHE[hostname] = (ip, now + _DNS_CACHE_TTL)
    return ip or hostname


def optimize_tcp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "SIO_KEEPALIVE_VALS") and os.name == 'nt':
            try: sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10000, 2000))
            except Exception: pass
        elif hasattr(socket, "TCP_KEEPIDLE"):
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
                if hasattr(socket, "TCP_KEEPINTVL"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
                if hasattr(socket, "TCP_KEEPCNT"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
            except Exception: pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
    except Exception:
        pass


def optimize_udp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
        if hasattr(socket, 'SIO_UDP_CONNRESET') and os.name == 'nt':
            try: sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception: pass
    except Exception:
        pass


async def safe_close_writer(writer):
    if not writer:
        return
    try:
        if not writer.is_closing():
            writer.close()
        await asyncio.wait_for(writer.wait_closed(), timeout=1.5)
    except Exception:
        pass


async def aes_encrypt(payload, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(payload, AES.block_size))


async def get_playstore_version():
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: play_scraper('com.dts.freefireth', lang='hi', country='id')
        )
        return result.get("version")
    except Exception:
        return "1.132.8"


async def version_config():
    app_version = await get_playstore_version()
    api_url = (
        "https://version.ggwhitehawk.com/live/ver.php"
        f"?version={app_version}"
        "&lang=hi&device=android&channel=android"
        "&appstore=googleplay&region=ME"
        "&whitelist_version=1.3.0&whitelist_sp_version=1.0.0"
    )
    try:
        response = await client.get(api_url)
        response.raise_for_status()
        data = response.json()
        server_url = data.get("server_url")
        remote_version = data.get("remote_version")
        latest_release_version = data.get("latest_release_version")
        if not server_url or not remote_version or not latest_release_version:
            return None
        return latest_release_version, remote_version, server_url
    except Exception:
        return None


async def get_access_token(uid, password):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    hdrs = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close"
    }
    data = {
        "uid": uid, "password": password,
        "response_type": "token", "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    for attempt in range(5):
        try:
            response = await client.post(url, headers=hdrs, data=data)
            if response.status_code == 200:
                rd = response.json()
                open_id = rd.get("open_id")
                access_token = rd.get("access_token")
                platform = rd.get("platform", 4)
                if open_id and access_token:
                    return open_id, access_token, platform
            if response.status_code == 429:
                await asyncio.sleep(1)
                continue
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return None


async def parse_results(parsed_results):
    result_dict = {}
    for result in parsed_results:
        field_data = {"wire_type": result.wire_type}
        if result.wire_type in ("varint", "string", "bytes"):
            field_data["data"] = result.data
        elif result.wire_type == "length_delimited":
            if hasattr(result.data, "results"):
                field_data["data"] = await parse_results(result.data.results)
            elif isinstance(result.data, list):
                field_data["data"] = await parse_results(result.data)
            else:
                field_data["data"] = str(result.data)
        result_dict[str(result.field)] = field_data
    return result_dict


async def decode_protobuf(data):
    parsed_results = Parser().parse(data)
    parsed_results_dict = await parse_results(parsed_results)
    return json.dumps(parsed_results_dict)


async def build_majorlogin_payload(open_id, access_token, platform, client_version, device_info, verr=None):
    try:
        if verr is None:
            verr = client_version
        proto = thunderFF_pb2.MajorLoginReq()
        proto.event_time = str(datetime.now())[:-7]
        proto.game_name = "free fire"
        proto.platform_id = 1
        proto.client_version = str(verr)
        proto.client_version_code = "2019121229"
        proto.system_software = "Android OS 15 / API-35 (AP3A.240905.015.A2/185014)"
        proto.system_hardware = "Handheld"
        proto.device_type = "Handheld"
        proto.screen_width = 1600
        proto.screen_height = 719
        proto.screen_dpi = "234"
        proto.processor_details = "ARM64 FP ASIMD AES | 1820 | 8"
        proto.memory = 2798
        proto.gpu_renderer = "Mali-G57"
        proto.gpu_version = "OpenGL ES 3.2 v1.r49p1-04eac0.2848c17a2fd4e9340e06555168eaa3c9"
        proto.unique_device_id = "Google|f744e396-5694-4e65-995d-97a958f2bd1f"
        proto.client_ip = "197.0.137.129"
        proto.language = "pt-br"
        proto.open_id = str(open_id)
        proto.open_id_type = "4"
        proto.login_open_id_type = 4
        proto.access_token = str(access_token)
        proto.login_by = 2
        proto.platform_sdk_id = 1
        proto.origin_platform_type = "4"
        proto.primary_platform_type = "4"
        proto.reg_avatar = 1
        proto.channel_type = 3
        proto.telecom_operator = "TUNTEL"
        proto.network_operator_a = "TUNTEL"
        proto.network_type = "WIFI"
        proto.network_type_a = "WIFI"
        proto.cpu_type = 2
        proto.cpu_architecture = "64"
        proto.graphics_api = "OpenGLES2"
        proto.supported_astc_bitset = 8191
        proto.client_using_version = "7428b253defc164018c604a1ebbfebdf"
        proto.loading_time = 15078
        proto.release_channel = "android"
        proto.extra_info = "KqsHTx3+QOmBRR1WKvaWewlcpqJBfjki+PPHQoQG8+0yV+Uos7gUFFjHMQ/e7u6han6Fl77r7c3vMN3p8UbKgN+nfycQCgwBmWgBzomx2gj84c+p"
        proto.android_engine_init_flag = 111207
        proto.if_push = 1
        proto.is_vpn = 0

        memory_available = proto.memory_available
        memory_available.version = 55
        memory_available.hidden_value = 81

        proto.external_storage_total = 49973
        proto.external_storage_available = 11338
        proto.internal_storage_total = 854
        proto.internal_storage_available = 11466
        proto.game_disk_storage_total = 49973
        proto.game_disk_storage_available = 11466
        proto.external_sdcard_total_storage = 49973
        proto.external_sdcard_avail_storage = 11466

        proto.library_path = "/data/app/~~lHFxTCCbupG2QVJmsURtZw==/com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/lib/arm64"
        proto.library_token = "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~lHFxTCCbupG2QVJmsURtZw==/com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/base.apk"

        base_payload = proto.SerializeToString()
        extra = b""
        extra += _pb_field(96, '{"cur_rate":[90,60,120],"support_etc2":false}')
        extra += _pb_field(97, 1)
        extra += _pb_field(99, "4")
        extra += _pb_field(100, "4")
        extra += _pb_field(102, b"\x17]ENWU\x0eR5")
        extra += _pb_field(104, 52882)
        extra += _pb_field(105, 1)
        extra += _pb_field(106, "https://dl.ak.freefiremobile.com/live/ABHotUpdates/|https://core-ak.freefiremobile.com/live/ABHotUpdates/|6b2078db9d22dd98f8e9386a39af8462")
        extra += _pb_field(107, "c8e41b7a93f02d56e1a94c7b8203f5d1")

        full_payload = base_payload + extra
        return await aes_encrypt(full_payload, AES_KEY, AES_IV)
    except Exception:
        return None


async def send_majorlogin(data, release_version, server_url):
    try:
        url = f"{server_url}MajorLogin" if server_url.endswith('/') else f"{server_url}/MajorLogin"
        req_headers = headers.copy()
        req_headers["ReleaseVersion"] = str(release_version)
        response = await client.post(url, headers=req_headers, data=data)
        if response.status_code != 200:
            return None
        response_content = response.content
        if len(response_content) < 40:
            return None

        res_proto = thunderFF_pb2.MajorLoginRes()
        try:
            res_proto.ParseFromString(response_content)
        except Exception:
            pass

        dict_res = {}
        try:
            parsed = Parser().parse(response_content.hex())
            dict_res = await parse_results(parsed)
        except Exception:
            pass

        key_val = get_proto_field(dict_res, 22)
        iv_val = get_proto_field(dict_res, 23)
        if not key_val:
            key_val = res_proto.aes_ak
        if not iv_val:
            iv_val = res_proto.iv_i

        if isinstance(key_val, str):
            try: key_val = bytes.fromhex(key_val)
            except Exception: pass
        if isinstance(iv_val, str):
            try: iv_val = bytes.fromhex(iv_val)
            except Exception: pass

        if not key_val or not iv_val:
            for offset in range(min(128, len(response_content))):
                try:
                    candidate = thunderFF_pb2.MajorLoginRes()
                    candidate.ParseFromString(response_content[offset:])
                    if candidate.region and candidate.token:
                        res_proto = candidate
                        break
                except Exception:
                    pass
            try:
                parsed = Parser().parse(response_content.hex())
                dict_res = await parse_results(parsed)
                kv = get_proto_field(dict_res, 22)
                ivv = get_proto_field(dict_res, 23)
                if isinstance(kv, str):
                    try: kv = bytes.fromhex(kv)
                    except Exception: pass
                if isinstance(ivv, str):
                    try: ivv = bytes.fromhex(ivv)
                    except Exception: pass
                if kv: key_val = kv
                if ivv: iv_val = ivv
            except Exception:
                pass

        if key_val:
            try: res_proto.aes_ak = key_val
            except Exception: pass
        if iv_val:
            try: res_proto.iv_i = iv_val
            except Exception: pass

        return res_proto
    except Exception as e:
        log(f"[-] send_majorlogin error: {e}")
        return None


async def send_getlogin(data, base_url, token, release_version):
    try:
        url = f"{base_url.rstrip('/')}/GetLoginData"
        req_headers = headers.copy()
        req_headers["ReleaseVersion"] = release_version
        req_headers['Authorization'] = f"Bearer {token}"
        req_headers['Host'] = "clientbp.ppmainecoonghj.com"
        response = await client.post(url, headers=req_headers, data=data)
        if response.status_code != 200:
            return None
        response_content = response.content

        res_proto = thunderFF_pb2.GetLoginDataRes()
        try:
            res_proto.ParseFromString(response_content)
        except Exception:
            pass

        def _extract_addr(raw_bytes, field_no):
            try:
                pos = 0
                n = len(raw_bytes)
                def read_varint(buf, p):
                    res = 0
                    sh = 0
                    while p < len(buf):
                        b = buf[p]
                        p += 1
                        res |= (b & 0x7F) << sh
                        if not (b & 0x80):
                            break
                        sh += 7
                    return res, p
                fields = {}
                while pos < n:
                    try:
                        key, pos = read_varint(raw_bytes, pos)
                    except Exception:
                        break
                    fn = key >> 3
                    wt = key & 0x07
                    try:
                        if wt == 0:
                            val, pos = read_varint(raw_bytes, pos)
                        elif wt == 2:
                            ln, pos = read_varint(raw_bytes, pos)
                            val = raw_bytes[pos:pos + ln]
                            pos += ln
                        elif wt == 5:
                            val = raw_bytes[pos:pos + 4]
                            pos += 4
                        elif wt == 1:
                            val = raw_bytes[pos:pos + 8]
                            pos += 8
                        else:
                            break
                    except Exception:
                        break
                    fields.setdefault(fn, []).append(val)
                if field_no in fields:
                    v = fields[field_no][0]
                    if isinstance(v, bytes):
                        try:
                            return v.decode('utf-8', 'ignore')
                        except Exception:
                            return None
                    return str(v)
            except Exception:
                return None

        try:
            for offset in range(0, min(80, len(response_content))):
                fa = _extract_addr(response_content[offset:], 14)
                ia = _extract_addr(response_content[offset:], 32)
                if fa and ":" in fa and ia and ":" in ia:
                    res_proto.functional_addrs = fa
                    res_proto.informational_addrs = ia
                    break
        except Exception:
            pass

        dict_res = {}
        try:
            parsed = Parser().parse(response_content.hex())
            dict_res = await parse_results(parsed)
        except Exception:
            pass

        return res_proto, dict_res
    except Exception as e:
        log(f"[-] send_getlogin error: {e}")
        return None


async def build_tcp_startup_packet(account_id, token, server_time, key, iv, region="ME", typ='OnLine'):
    uid_hex = f"{int(account_id):016x}"
    timestamp_hex = f"{int(server_time):08x}"
    encode_token = token.encode()
    encrypted_packet = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(encode_token, 16)).hex()
    encrypted_packet_length = f"{len(encrypted_packet) // 2:08x}"
    if typ == 'OnLine':
        return f"9015{uid_hex}{timestamp_hex}00000000{encrypted_packet_length}{encrypted_packet}"
    else:
        return f"9015{uid_hex}{timestamp_hex}{encrypted_packet_length}{encrypted_packet}"


async def send_keep_alive(region="ME"):
    try:
        reg = str(region).upper() if region else "ME"
        ka_hex = "0219" if reg == "ME" else ("0214" if reg == "IND" else "0215")
        return bytes.fromhex(ka_hex)
    except Exception:
        return bytes.fromhex("0219")


async def start_game_match_search(mode, region, client_version, writer, key, iv):
    packet = bytes.fromhex("080112800a0a010110013a110a044944433110aa011a064555524f50453a100a044944433210311a064555524f504540014a0801090a0b1219202758016291090a8001303838463832424630324139363736373032303130313030303030303030303030303136303030313030313530303032323246393745454530463030303030303436373632353134303030303030303030303030303030303030303030303030303030303030303030303030303066663030303030303030636163666131366410241afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e75196001477c015165406370195f5547404e4550640103020f1304064863754268676c755f65576e40467e5f0a417a4701026d675d6e73670b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b625f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d615f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e5078487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b441b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0a167305067162727516134208312e3133302e3232480350015ae90403626253513635686e556f4e36416456324b796f566c636f477776484f624e56526c4d727073504b4f43654177616848494176795556497273743752737149734a7a786b3247525268377a2f637664626d504f6a73552f79626d38547a4c69586d2f474351696d494b53486833447955726f39515152756c34545350626d6d624b7949565937545671577059455372323646572f59624578507338514f706d317372785455736c30796a434144444d4f34616a654b615753366361496c554b4963797a494e396d52516f715277687939797257476d337a644345337a6a61436f492f5a585233656f65365a42647a64677654636b6b665733356e4d4c6a6a565072564b6433523172756174394e50514150724a5546627859696c4c5a3859707336654d5447666b6649793574666a526c314d4648706b51774c6373374439656378566c41636f374e664f6d2b30654756466c4434744478706771385533595973587645384842502f70666c767a737138316a32524f4d7857437556445442492f684735625462773166456e4249725162762b636144775147696f74554e316d4c4b77734379456f4766706746614251457645672b736a764c4c78704743334c304a5344532f74526169504354553344374e6249306547516651622f5a466f4c36455630775a324d6f583932414c572f5049752f56634663584e70596b356f7966326151416a536971486a2f363276354843644f525551303578754e6171795251625653704654303137655237675255636b4966366c6f447476342b514e4a4670766d74757077707774396a5a5974437a4b56743657726d6e36785837706658456251555434684f3758a201050803108703a201050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815")
    proto = thunderFF_pb2.StartMatch()
    proto.ParseFromString(packet)
    if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = region
    if hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = client_version
    packet = proto.SerializeToString()
    encrypted_packet = (await aes_encrypt(packet, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = hex(packet_length)[2:]
    hex_length = hex_length if len(hex_length) > 1 else "0" + hex_length
    reg = str(region).upper() if region else "ME"
    reg_prefix = "031900" if reg == "ME" else ("031400" if reg == "IND" else "031500")
    final_packet = reg_prefix + "0" * (6 - len(hex_length)) + hex_length + encrypted_packet
    writer.write(bytes.fromhex(final_packet))
    await writer.drain()
    log(f"[{str(mode).upper()}] Match search request sent ({packet_length} bytes) | Region: {reg}")


def has_ssan_zig(n):
    z = (n << 1) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while z >= 0x80:
        out.append((z & 0x7F) | 0x80)
        z >>= 7
    out.append(z)
    return bytes(out)


async def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v1 = (v1 + (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
    return v0, v1


async def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v0 = (v0 - (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1


async def tea_cbc_encrypt(padded, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(padded))
    prev_cipher = bytearray(8)
    prev_intermediate = bytearray(8)
    for i in range(0, len(padded), 8):
        xored = bytearray(8)
        for j in range(8):
            xored[j] = padded[i + j] ^ prev_cipher[j]
        e0, e1 = await tea_enc(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3,
        )
        enc = bytearray(8)
        struct.pack_into("<I", enc, 0, e0)
        struct.pack_into("<I", enc, 4, e1)
        for j in range(8):
            out[i + j] = enc[j] ^ prev_intermediate[j]
        prev_cipher[:] = out[i:i + 8]
        prev_intermediate[:] = xored
    return bytes(out)


async def build_padded(content):
    pad_len = (8 - (len(content) + 10) % 8) % 8
    return bytes([pad_len, 0, 0]) + b"\x00" * pad_len + content + b"\x00" * 7


async def encode_header(layout, send_option, cmd, order_id, flags, length, k, v80):
    out = bytearray()
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: length}[code]
        if _FIELD_SIZES[code] == 1:
            out.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            out.append(v & 0xFF)
            out.append((v >> 8) & 0xFF)
    return bytes(out)


async def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F


async def sv_frame(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0]) + await encode_header(layout, send_option, cmd, order_id, flags, len(body), k, v80)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)


async def build_match_startup_packets(token, udp_key, match_code, account_id, block_val,
                                      server_ip="", region="ME", client_version="1.132.8",
                                      client_version_code="2019121229", access_token="",
                                      mode_id=MODE_ID, map_id=MAP_ID):
    token = token.strip()
    udp_key = bytes.fromhex(udp_key)
    match_code = [int(ch) for ch in str(match_code).strip()]

    thunder_jwt = token[:660] if len(token) > 660 else token
    sharma_jwt = token[660:] if len(token) > 660 else ""
    encoded_thunder_jwt = thunder_jwt.encode() if isinstance(thunder_jwt, str) else thunder_jwt
    encoded_sharma_jwt = sharma_jwt.encode() if isinstance(sharma_jwt, str) else sharma_jwt

    garena420 = has_ssan_zig(len(encoded_thunder_jwt)) + encoded_thunder_jwt
    reg = str(region).upper() if region else "ME"

    csoversea_block = bytes.fromhex(
        "ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
        "3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e"
        "3137302e3233303b33352e3138352e3138332e35370000000000000100000000000000000000000001"
        "00000800000100000000000100a8a2d7bebd8d8bdf110200"
    )

    mid = bytes.fromhex('0000000001000102030101') + has_ssan_zig(len(reg)) + reg.encode()
    mid += bytes.fromhex('0001030003000004')
    mid += has_ssan_zig(len(client_version)) + client_version.encode()
    mid += has_ssan_zig(len(client_version_code)) + client_version_code.encode()
    mid += csoversea_block

    clean_ip = server_ip.split(':')[0] if server_ip else "0.0.0.0"
    mid += has_ssan_zig(len(clean_ip)) + clean_ip.encode()

    clean_acc_tok = access_token.strip() if access_token else ""
    if clean_acc_tok:
        mid += has_ssan_zig(len(clean_acc_tok)) + clean_acc_tok.encode()

    mid += has_ssan_zig(len(encoded_sharma_jwt)) + encoded_sharma_jwt

    tg_garena420 = (
        uleb_encode(int(account_id)) +
        uleb_encode(int(block_val)) +
        uleb_encode(1) +
        uleb_encode(int(mode_id)) +
        uleb_encode(int(block_val)) +
        uleb_encode(int(map_id)) +
        mid
    )

    process = await sv_frame(0x5E, match_code, 2, 447, 0, 1, garena420, udp_key)
    loading = await sv_frame(0x5A, match_code, 2, 448, 1, 1, tg_garena420, udp_key)
    return process.hex(), loading.hex()


async def produce_xor_key(secret_key):
    k = secret_key[0] if secret_key and len(secret_key) > 0 else 10
    return k, ((k << 8) | k) & 0xFFFF


async def parse_layout(layout):
    if isinstance(layout, str):
        return [int(ch) for ch in layout.strip()]
    return list(layout)


async def tea_cbc_decrypt(body, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(body))
    prev_intermediate = bytearray(8)
    prev_cipher = bytearray(8)
    xored = bytearray(8)
    dec = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8):
            xored[j] = body[i + j] ^ prev_intermediate[j]
        d0, d1 = await tea_dec(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3
        )
        struct.pack_into("<I", dec, 0, d0)
        struct.pack_into("<I", dec, 4, d1)
        for j in range(8):
            out[i + j] = dec[j] ^ prev_cipher[j]
        prev_cipher[:] = body[i:i + 8]
        prev_intermediate[:] = dec
    return bytes(out)


async def build_hello_packet(text, key, layout):
    data = text.encode("utf-8")
    if len(data) > 25:
        raise ValueError(f"Text is too long ({len(data)} bytes)")
    content = b"\x10\x00\x00\x00" + data + b"\x00" * (29 - 4 - len(data))
    k, v80 = await produce_xor_key(key)
    layout = await parse_layout(layout)
    padded = await build_padded(content)
    enc_body = await tea_cbc_encrypt(padded, key)
    header_bytes = await encode_header(layout, 1, 1, 0, 1, len(enc_body), k, v80)
    packet = bytearray([0x63, 0x00]) + header_bytes + enc_body
    packet[1] = await crc7_buff(0, packet[2:]) & 0x7F
    return bytes(packet).hex()


async def classify(frame):
    cmd = frame["cmd"]
    msg_name = MESSAGE_ID_TO_NAME.get(cmd, f"UNKNOWN_{cmd}")
    if msg_name == "UDP_HELLO":
        return "HELLO"
    if msg_name == "UDP_ACK":
        return "ACK"
    if msg_name == "UDP_PING":
        return "PING"
    if msg_name == "RUDP_JOIN_MATCH":
        return "JOIN_MATCH"
    if msg_name.startswith("RUDP_"):
        return msg_name
    if msg_name.startswith("UDP_"):
        return msg_name
    return "DATA"


async def build_packet(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0])
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: len(body)}[code]
        if _FIELD_SIZES[code] == 1:
            hdr.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            hdr.append(v & 0xFF)
            hdr.append((v >> 8) & 0xFF)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)


async def layouts_from_mask(mask):
    ru = [int(c) for c in str(mask).strip()]
    nr = [c for c in ru if c != 2]
    return ru, nr


async def reply_for(frame, key, mask, ack_key=0x68, ping_key=0x6D, hello_key=0x5B, ack_style="short"):
    ru, nr = await layouts_from_mask(mask)
    typ = await classify(frame)
    if typ == "HELLO":
        if ack_style == "echo":
            content = frame["content"] if frame["content"] else b"\x10\x00\x00\x00"
            return typ, await build_packet(hello_key, nr, 1, 1, None, 1, content, key)
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x01\x00", key)
    if typ == "ACK":
        content = frame["content"] if frame["content"] else b"\x01\x00"
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, content, key)
    if typ == "PING":
        c = frame["content"]
        counter = c[:4] if len(c) >= 4 else c
        return typ, await build_packet(ping_key, nr, 0, 3, None, 0, counter + b"\x00\x00\x00", key, encrypted=False)
    if typ == "JOIN_MATCH":
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x02\x00", key)
    return typ, None


async def keepalive_ping(sock, ip, port, key_bytes, mask, stop_event):
    nr = (await layouts_from_mask(mask))[1]
    ping_keys = [0x66, 0x6D, 0x69, 0x6C, 0x6B, 0x6E, 0x6F, 0x70]
    loop = asyncio.get_event_loop()
    i = 0
    while not stop_event.is_set():
        pk = ping_keys[i % len(ping_keys)]
        counter = int(time.time() * 1000) & 0xFFFFFFFF
        pkt = await build_packet(pk, nr, 0, 3, None, 0, struct.pack("<I", counter) + b"\x00\x00\x00", key_bytes, encrypted=False)
        try:
            await loop.sock_sendto(sock, pkt, (ip, port))
        except Exception:
            pass
        i += 1
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass


async def try_header(buf, layout, k, v80):
    off = 2
    out = {}
    for code in layout:
        size = _FIELD_SIZES[code]
        if off + size > len(buf):
            return None
        out[_FIELD_NAMES[code]] = (buf[off] ^ k) if size == 1 else ((buf[off] | (buf[off + 1] << 8)) ^ v80) & 0xFFFF
        off += size
    out["headerLen"] = off
    return out


async def oicq_unpad(padded):
    if not padded or len(padded) < 8:
        return None
    if not all(padded[-1 - i] == 0 for i in range(7)):
        return None
    pad_len = padded[0] & 0x07
    s = 3 + pad_len
    e = len(padded) - 7
    return padded[s:e] if s < e else b""


async def decode_packet(packet, key, mask=None):
    data = bytes(packet) if isinstance(packet, bytes) else bytes.fromhex(packet)
    if len(data) < 8:
        return None
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    crc_ok = (data[1] & 0x7F) == await crc7_buff(0, data[2:])
    candidates = []
    if mask:
        ru, nr = await layouts_from_mask(mask)
        layouts = [("RUDP", ru), ("nonRUDP", nr)]
    else:
        layouts = [("RUDP", list(p)) for p in itertools.permutations([0, 1, 2, 3, 4])]
        layouts += [("nonRUDP", list(p)) for p in itertools.permutations([0, 1, 3, 4])]
    for kind, layout in layouts:
        f = await try_header(data, layout, k, v80)
        if not f:
            continue
        if f["flags"] > 7 or f["sendOption"] > 7:
            continue
        if f["length"] != len(data) - f["headerLen"]:
            continue
        body = data[f["headerLen"]:f["headerLen"] + f["length"]]
        content = None
        padded = None
        if f["flags"] & 1:
            if len(body) < 8 or len(body) % 8 != 0:
                continue
            padded = await tea_cbc_decrypt(body, key)
            content = await oicq_unpad(padded)
            if content is None:
                continue
        else:
            content = body
        score = (1 if crc_ok else 0) + (1 if content is not None else 0)
        candidates.append({
            "kind": kind, "layout": layout, "headerLen": f["headerLen"],
            "msgKey": data[0], "cmd": f["cmd"], "flags": f["flags"],
            "sendOption": f["sendOption"], "orderId": f.get("orderId"),
            "length": f["length"], "content": content, "crcOk": crc_ok,
            "padded": padded, "score": score, "total": len(data),
        })
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["kind"] == "RUDP" or c["kind"] == "nonRUDP", c["score"]), reverse=True)
    return candidates[0]


async def play_game(server_ip_port, thunder, sharma, udp_key, match_code,
                    account_id, player_region, client_version, key, iv,
                    match_index: int):
    match_start_time = time.time()
    ping_task = None
    sock = None
    ping_stop = asyncio.Event()
    uid_str = str(account_id)
    completed_cleanly = False

    try:
        ip, port = server_ip_port.split(":")
        port = int(port)
        resolved_ip = await resolve_host_cloudflare(ip)

        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(('0.0.0.0', 0))
        except Exception:
            pass
        optimize_udp_socket(sock)
        sock.setblocking(False)

        udp_key_bytes = bytes.fromhex(udp_key)
        hello_packet = await build_hello_packet(f"{account_id}_2585", udp_key_bytes, match_code)
        try:
            await loop.sock_sendto(sock, bytes.fromhex(hello_packet), (resolved_ip, port))
            log(f"[MATCH #{match_index}] [SEND-OK] HELLO size={len(bytes.fromhex(hello_packet))}B -> {(resolved_ip, port)}")
        except Exception as e:
            log(f"[MATCH #{match_index}] [SEND-FAIL] HELLO: {e}")

        ack_state = "waiting_for_hello_reply"
        thunder_sent = False
        sharma_sent = False
        join_match_received = False
        local_closed = False
        send_lock = asyncio.Lock()

        ping_task = asyncio.create_task(
            keepalive_ping(sock, resolved_ip, port, udp_key_bytes, match_code, ping_stop)
        )

        last_activity = time.time()
        MAX_IDLE_BEFORE_HELLO_RESEND = 7.0

        async def send_thunder_sharma_inline():
            nonlocal ack_state, thunder_sent, sharma_sent
            if thunder_sent:
                return
            async with send_lock:
                if thunder_sent:
                    return
                try:
                    thunder_b = bytes.fromhex(thunder)
                    await loop.sock_sendto(sock, thunder_b, (resolved_ip, port))
                    log(f"[MATCH #{match_index}] [SEND-OK] THUNDER size={len(thunder_b)}B -> {(resolved_ip, port)}")
                    thunder_sent = True

                    await asyncio.sleep(0.3)

                    prepare_ack = await build_packet(
                        0x68, (await layouts_from_mask(match_code))[1],
                        0, 2, None, 1, b"\x01\x00", udp_key_bytes
                    )
                    await loop.sock_sendto(sock, prepare_ack, (resolved_ip, port))
                    log(f"[MATCH #{match_index}] [SEND-OK] PREPARE_ACK size={len(prepare_ack)}B -> {(resolved_ip, port)}")

                    await asyncio.sleep(0.4)

                    sharma_b = bytes.fromhex(sharma)
                    await loop.sock_sendto(sock, sharma_b, (resolved_ip, port))
                    log(f"[MATCH #{match_index}] [SEND-OK] SHARMA size={len(sharma_b)}B -> {(resolved_ip, port)}")

                    sharma_sent = True
                    ack_state = "thunder_sharma_sent"
                    log(f"[MATCH #{match_index}] Startup delivered. Playing.")
                except Exception as e:
                    log(f"[MATCH #{match_index}] [SEND-FAIL] Startup: {e}")

        while not local_closed:
            elapsed = time.time() - match_start_time
            if elapsed > MAX_MATCH_DURATION:
                completed_cleanly = True
                break

            try:
                response, server_addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65535), timeout=2.0
                )
                if response:
                    last_activity = time.time()
                    frame = await decode_packet(response, udp_key_bytes, match_code)
                    if frame:
                        ptype = await classify(frame)
                        cmd = frame['cmd']

                        if cmd in [103, 107]:
                            log(f"[★] Match #{match_index} finished (cmd {cmd})")
                            completed_cleanly = True
                            local_closed = True
                            continue

                        if cmd == 101:
                            try:
                                ack_pkt = await build_packet(
                                    0x68, (await layouts_from_mask(match_code))[1],
                                    0, 2, None, 1, b"\x01\x00", udp_key_bytes
                                )
                                await loop.sock_sendto(sock, ack_pkt, server_addr)
                                log(f"[MATCH #{match_index}] [SEND-OK] ACK-101 size={len(ack_pkt)}B -> {server_addr}")
                            except Exception as e:
                                log(f"[MATCH #{match_index}] [SEND-FAIL] ACK-101: {e}")

                        if ptype in ["ACK", "PING", "HELLO", "JOIN_MATCH"]:
                            if ptype == "HELLO" and ack_state == "waiting_for_hello_reply":
                                typ, reply = await reply_for(
                                    frame, udp_key_bytes, match_code, ack_style="short"
                                )
                                if reply:
                                    try:
                                        await loop.sock_sendto(sock, reply, server_addr)
                                        log(f"[MATCH #{match_index}] [SEND-OK] HELLO-REPLY size={len(reply)}B -> {server_addr}")
                                    except Exception as e:
                                        log(f"[MATCH #{match_index}] [SEND-FAIL] HELLO-REPLY: {e}")
                                ack_state = "ack_sent_waiting"
                            elif ptype == "ACK":
                                if ack_state == "waiting_for_hello_reply":
                                    typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                    if reply:
                                        try:
                                            await loop.sock_sendto(sock, reply, server_addr)
                                            log(f"[MATCH #{match_index}] [SEND-OK] ACK-REPLY size={len(reply)}B -> {server_addr}")
                                        except Exception as e:
                                            log(f"[MATCH #{match_index}] [SEND-FAIL] ACK-REPLY: {e}")
                                    ack_state = "ready_to_send_thunder"
                                elif ack_state == "ack_sent_waiting":
                                    ack_state = "ready_to_send_thunder"
                                else:
                                    typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                    if reply:
                                        try:
                                            await loop.sock_sendto(sock, reply, server_addr)
                                            log(f"[MATCH #{match_index}] [SEND-OK] ACK-REPLY size={len(reply)}B -> {server_addr}")
                                        except Exception as e:
                                            log(f"[MATCH #{match_index}] [SEND-FAIL] ACK-REPLY: {e}")
                            elif ptype == "PING":
                                typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                if reply:
                                    try:
                                        await loop.sock_sendto(sock, reply, server_addr)
                                        log(f"[MATCH #{match_index}] [SEND-OK] PING-REPLY size={len(reply)}B -> {server_addr}")
                                    except Exception as e:
                                        log(f"[MATCH #{match_index}] [SEND-FAIL] PING-REPLY: {e}")
                            elif ptype == "JOIN_MATCH" and not join_match_received:
                                typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                if reply:
                                    try:
                                        await loop.sock_sendto(sock, reply, server_addr)
                                        log(f"[MATCH #{match_index}] [SEND-OK] JOIN-MATCH-REPLY size={len(reply)}B -> {server_addr}")
                                    except Exception as e:
                                        log(f"[MATCH #{match_index}] [SEND-FAIL] JOIN-MATCH-REPLY: {e}")
                                    join_match_received = True

            except asyncio.TimeoutError:
                if ack_state == "ready_to_send_thunder" and not thunder_sent:
                    await send_thunder_sharma_inline()
                elif ack_state == "waiting_for_hello_reply":
                    if (time.time() - last_activity) > MAX_IDLE_BEFORE_HELLO_RESEND:
                        try:
                            pkt = await build_hello_packet(
                                f"{account_id}_2585", udp_key_bytes, match_code
                            )
                            await loop.sock_sendto(sock, bytes.fromhex(pkt), (resolved_ip, port))
                            log(f"[MATCH #{match_index}] [SEND-OK] HELLO-RESEND size={len(bytes.fromhex(pkt))}B -> {(resolved_ip, port)}")
                        except Exception as e:
                            log(f"[MATCH #{match_index}] [SEND-FAIL] HELLO-RESEND: {e}")
                        last_activity = time.time()
                    if (time.time() - match_start_time) > 25.0:
                        break

            except BlockingIOError:
                await asyncio.sleep(0.05)
            except OSError:
                await asyncio.sleep(0.5)
                continue
            except Exception:
                await asyncio.sleep(0.5)
                continue

            if ack_state == "ready_to_send_thunder" and not thunder_sent:
                await send_thunder_sharma_inline()

        return f"match #{match_index} finished"

    except Exception as e:
        log(f"[MATCH #{match_index}] Session error: {e}")
        return f"match #{match_index} error"

    finally:
        ping_stop.set()
        if ping_task:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        if sock:
            try:
                sock.close()
            except Exception:
                pass


async def functional_br(addrs, starter_packet, account_region, client_version,
                        key, iv, account_id="", account_data=None,
                        max_reconnects=10):
    reconnects = 0
    ip, port = addrs.split(":")
    play_matches: List[asyncio.Task] = []
    no_response_count = 0
    uid_str = str(account_id)

    current_token = starter_packet
    current_key = key
    current_iv = iv
    current_account_data = account_data

    try:
        while True:
            await squad_coordinator.wait_if_held(uid_str)
            writer = None
            gateway_ping_task = None
            try:
                resolved_ip = await resolve_host_cloudflare(ip)
                reader, writer = await asyncio.open_connection(resolved_ip, int(port))

                raw_sock = writer.get_extra_info('socket')
                if raw_sock:
                    optimize_tcp_socket(raw_sock)

                writer.write(bytes.fromhex(current_token))
                await writer.drain()

                try:
                    init_ka = await send_keep_alive(account_region)
                    if init_ka and writer and not writer.is_closing():
                        writer.write(init_ka)
                        await asyncio.wait_for(writer.drain(), timeout=3)
                except Exception:
                    pass

                async def func_gateway_keepalive():
                    ka_bytes = await send_keep_alive(account_region)
                    while True:
                        await asyncio.sleep(5)
                        try:
                            if writer and not writer.is_closing():
                                writer.write(ka_bytes)
                                await writer.drain()
                        except Exception:
                            break

                gateway_ping_task = asyncio.create_task(func_gateway_keepalive())

                log(f"[+] TCP gateway connected | UID: {uid_str}")
                reconnects = 0
                no_response_count = 0

                session_info = {
                    "writer": writer,
                    "key": current_key,
                    "iv": current_iv,
                    "region": account_region,
                    "client_version": client_version,
                }
                live_gateway_sessions[uid_str] = session_info
                if squad_coordinator.is_active_member(uid_str):
                    await squad_coordinator.register_session(uid_str, session_info)
                    if uid_str != squad_coordinator.members[0]:
                        log(f"[SQUAD] UID {uid_str} aguardando convite/partida do líder; sem fila individual.")
                else:
                    log(f"[LOBBY] UID {uid_str} conectado e aguardando início manual da squad; matchmaking individual desativado.")

                gateway_receive_buffer = bytearray()
                while True:
                    play_matches[:] = [m for m in play_matches if not m.done()]

                    if squad_coordinator.should_migrate(uid_str, writer) and not play_matches:
                        break

                    try:
                        data = await asyncio.wait_for(
                            read_gateway_frame(reader, gateway_receive_buffer), timeout=0.5
                        )
                    except asyncio.TimeoutError:
                        no_response_count += 1
                        if no_response_count > 60:
                            no_response_count = 0
                        continue

                    if not data:
                        raise ConnectionError("Connection closed by server")

                    hex_data = data.hex()
                    packet_length = len(data)
                    no_response_count = 0

                    log(f"[DEBUG] UID {uid_str} recv len={packet_length} head={hex_data[:40]}")

                    if packet_length < 10:
                        continue

                    if hex_data.startswith("0f00") and squad_coordinator.is_active_member(uid_str):
                        status_info = await _parse_player_status_response(hex_data)
                        if status_info:
                            await squad_coordinator.handle_server_status(
                                status_info["uid"], status_info["status_code"],
                                status_info["leader_uid"], status_info["member_count"],
                                status_info["member_capacity"]
                            )
                            log(
                                f"[SQUAD] Resposta de status do servidor para {status_info['uid']}: "
                                f"state={status_info['status_code']} leader={status_info['leader_uid']} "
                                f"members={status_info['member_count']}/{status_info['member_capacity']}"
                            )
                        continue

                    if hex_data.startswith("0500"):
                        if squad_coordinator.is_active_member(uid_str):
                            try:
                                invite_data = json.loads(await decode_protobuf(hex_data[10:]))
                                inviter_uid = _nested_proto_value(invite_data, 5, 1)
                                target_uid = _nested_proto_value(invite_data, 5, 2, 1)
                                invite_code = _nested_proto_value(invite_data, 5, 8)
                                if inviter_uid is None or target_uid is None or invite_code is None:
                                    log(
                                        f"[DEBUG] Pacote 0500 de UID {uid_str} não tem os campos de convite "
                                        "(remetente/alvo/código); ignorado sem aceitar."
                                    )
                                    continue
                                accepted = await squad_coordinator.accept_group_invite(
                                    uid_str, inviter_uid, target_uid, invite_code, session_info
                                )
                                if accepted:
                                    log(f"[SQUAD] UID {uid_str} aceitou convite permitido do líder {inviter_uid}.")
                            except Exception as exc:
                                log(f"[SQUAD] Pacote de convite ignorado para UID {uid_str}: {exc}")
                        continue

                    is_match_packet = False
                    payload_hex = None

                    if hex_data.startswith("0300"):
                        if 10 < packet_length < 30:
                            log(f"[*] Queue confirmed ({squad_coordinator.mode}) | UID: {uid_str}")
                            continue
                        elif packet_length >= 300:
                            is_match_packet = True
                            payload_hex = hex_data[10:]
                        else:
                            continue
                    elif packet_length >= 200:
                        is_match_packet = True
                        payload_hex = hex_data

                    if not is_match_packet:
                        continue

                    log(f"[DEBUG] Candidato a resposta de partida {squad_coordinator.mode} | UID: {uid_str} | size={packet_length}")

                    try:
                        res = json.loads(await decode_protobuf(payload_hex))
                        token = None
                        udp_key = None
                        match_code = None
                        server_ip_port = None
                        match_account_id = None
                        block_val = None

                        if '42' in res and 'data' in res['42']:
                            match_code = res['42']['data']
                        if '5' in res and 'data' in res['5']:
                            res_field5 = res['5']['data']
                            server_ip_port = res_field5.get('2', {}).get('data')
                            udp_key = res_field5.get('3', {}).get('data')
                            token = res_field5.get('4', {}).get('data')
                            if '42' in res_field5:
                                match_code = res_field5['42']['data']
                        if '1' in res and 'data' in res['1']:
                            match_account_id = res['1']['data']
                        if '5' in res and 'data' in res['5']:
                            block_val = res['5']['data'].get('1', {}).get('data')

                        effective_acc_id = match_account_id or account_id or "ME_BOT"

                        log(f"[DEBUG] UID {uid_str} parsed: token={'YES' if token else 'NO'} udp_key={'YES' if udp_key else 'NO'} match_code={'YES' if match_code else 'NO'} server={server_ip_port}")

                        if token and udp_key and match_code and server_ip_port:
                            log(f"[+] Match found [{squad_coordinator.mode}] | UID: {uid_str} | size={packet_length}")
                            await squad_coordinator.mark_match_found(uid_str)
                            acc_tok = current_account_data.get('access_token', '') if current_account_data else ""
                            match_mode_id, match_map_id = (CS_MODE_ID, CS_MAP_ID) if squad_coordinator.mode == "CS" else (MODE_ID, MAP_ID)

                            thunder, sharma = await build_match_startup_packets(
                                token, udp_key, match_code, effective_acc_id, block_val or 0,
                                server_ip=server_ip_port,
                                region=account_region,
                                client_version=client_version,
                                access_token=acc_tok,
                                mode_id=match_mode_id,
                                map_id=match_map_id
                            )

                            match_index = len(play_matches) + 1
                            log(f"[+] Match #{match_index} [BR] injected -> {server_ip_port}")

                            new_match = asyncio.create_task(
                                play_game(
                                    server_ip_port,
                                    thunder,
                                    sharma,
                                    udp_key,
                                    match_code,
                                    effective_acc_id,
                                    str(account_region or "BR").upper(),
                                    client_version,
                                    current_key,
                                    current_iv,
                                    match_index=match_index
                                )
                            )
                            play_matches.append(new_match)

                            async def drain_gateway_reader():
                                while not new_match.done():
                                    try:
                                        data_gw = await asyncio.wait_for(reader.read(4096), timeout=1.0)
                                        if not data_gw:
                                            break
                                    except asyncio.TimeoutError:
                                        continue
                                    except Exception:
                                        break

                            drain_task = asyncio.create_task(drain_gateway_reader())

                            try:
                                await new_match
                            except Exception as e:
                                log(f"[MATCH #{match_index}] error: {e}")
                            finally:
                                await squad_coordinator.mark_match_finished(uid_str)
                                drain_task.cancel()
                                try:
                                    await drain_task
                                except asyncio.CancelledError:
                                    pass

                            play_matches[:] = [m for m in play_matches if not m.done()]

                            try:
                                await refresh_account_profile(current_account_data)
                            except Exception:
                                pass

                            new_level = 1
                            if current_account_data:
                                new_level = max(1, int(current_account_data.get("level", 1) or 1))
                            log(f"[*] UID {uid_str} | Lvl {new_level} | Next: BR")

                            if gateway_ping_task:
                                gateway_ping_task.cancel()
                            await safe_close_writer(writer)
                            writer = None
                            break

                        else:
                            log(f"[DEBUG] UID {uid_str} not a valid match packet — ignoring")
                            continue

                    except Exception as e:
                        log(f"[!] Match packet notice: {e}")
                        continue

            except asyncio.CancelledError:
                if gateway_ping_task:
                    gateway_ping_task.cancel()
                raise
            except Exception as e:
                if gateway_ping_task:
                    gateway_ping_task.cancel()
                play_matches[:] = [m for m in play_matches if not m.done()]
                await safe_close_writer(writer)

                if "Cache expired" in str(e):
                    break

                reconnects += 1
                if reconnects > max_reconnects:
                    reconnects = 0
                    break

                await asyncio.sleep(min(reconnects * 0.5, 2.0))
            finally:
                if gateway_ping_task:
                    gateway_ping_task.cancel()
                if live_gateway_sessions.get(uid_str, {}).get("writer") is writer:
                    live_gateway_sessions.pop(uid_str, None)
                if writer:
                    await safe_close_writer(writer)

    except asyncio.CancelledError:
        raise
    finally:
        for m in play_matches:
            if not m.done():
                m.cancel()


async def informational(addrs, starter_packet, key, iv, region="ME", account_id="", max_reconnects=3):
    uid_str = str(account_id)
    reconnects = 0
    ip, port = addrs.split(":")
    while True:
        writer = None
        ping_task = None
        try:
            resolved_ip = await resolve_host_cloudflare(ip)
            reader, writer = await asyncio.open_connection(resolved_ip, int(port))

            raw_sock = writer.get_extra_info('socket')
            if raw_sock:
                optimize_tcp_socket(raw_sock)

            writer.write(bytes.fromhex(starter_packet))
            await writer.drain()
            reconnects = 0

            try:
                init_ka = await send_keep_alive(region)
                if init_ka and writer and not writer.is_closing():
                    writer.write(init_ka)
                    await asyncio.wait_for(writer.drain(), timeout=3)
            except Exception:
                pass

            async def info_keepalive():
                ka_bytes = await send_keep_alive(region)
                while True:
                    await asyncio.sleep(5)
                    try:
                        if writer and not writer.is_closing():
                            writer.write(ka_bytes)
                            await writer.drain()
                    except Exception:
                        break

            ping_task = asyncio.create_task(info_keepalive())

            chat_session = {
                "writer": writer,
                "key": key,
                "iv": iv,
                "region": region,
            }
            live_chat_sessions[uid_str] = chat_session
            if squad_coordinator.is_active_member(uid_str):
                await squad_coordinator.register_chat_session(uid_str, chat_session)

            while True:
                try:
                    data = await asyncio.wait_for(reader.read(8192), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if not data:
                    raise ConnectionError("Connection closed")
        except asyncio.CancelledError:
            if ping_task:
                ping_task.cancel()
            if live_chat_sessions.get(uid_str, {}).get("writer") is writer:
                live_chat_sessions.pop(uid_str, None)
            await squad_coordinator.unregister_chat_session(uid_str, writer)
            await safe_close_writer(writer)
            raise
        except Exception:
            if ping_task:
                ping_task.cancel()
            if live_chat_sessions.get(uid_str, {}).get("writer") is writer:
                live_chat_sessions.pop(uid_str, None)
            await squad_coordinator.unregister_chat_session(uid_str, writer)
            await safe_close_writer(writer)
            reconnects += 1
            if reconnects > max_reconnects:
                await asyncio.sleep(3)
                reconnects = 0
            else:
                await asyncio.sleep(1)


async def refresh_account_profile(account_data: Dict):
    try:
        if not account_data:
            return
        account_id = str(account_data.get('account_id', ''))
        timestamp = time.strftime("%H:%M:%S")
        url = account_data.get('server_url')
        token = account_data.get('token')
        release_version = account_data.get('release_version')
        payload = account_data.get('login_payload_data')
        if not (url and token and release_version and payload):
            if account_id in bot_state.accounts:
                bot_state.accounts[account_id].update({"exp_check_status": "sem dados de sessão", "exp_last_check": timestamp})
            return
        res = await send_getlogin(payload, url, token, release_version)
        if not res:
            if account_id in bot_state.accounts:
                bot_state.accounts[account_id].update({"exp_check_status": "falha na consulta", "exp_last_check": timestamp})
            bot_state.log(f"Consulta de EXP falhou para UID {account_id}", "warning", account_id)
            return
        res_proto, dict_res = res
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, "")
        if level <= 0:
            level = 1
        if exp < 0:
            exp = 0
        account_data['level'] = level
        account_data['exp'] = exp
        if account_id:
            bot_state.update_exp(account_id, exp, level)
            if account_id in bot_state.accounts:
                bot_state.accounts[account_id].update({
                    "exp_source": "sessão do jogo",
                    "exp_check_status": "atualizado",
                    "exp_last_check": timestamp
                })
            bot_state.log(f"EXP consultado pela sessão: nível {level}, EXP {exp}", "success", account_id)
        if nickname:
            account_data['nickname'] = nickname
    except Exception as exc:
        account_id = str(account_data.get('account_id', '')) if isinstance(account_data, dict) else ''
        timestamp = time.strftime("%H:%M:%S")
        if account_id in bot_state.accounts:
            bot_state.accounts[account_id].update({"exp_check_status": "erro interno", "exp_last_check": timestamp})
        log(f"[!] Falha ao consultar EXP ({type(exc).__name__}) para UID {account_id}")


PUBLIC_FF_API = "https://hostfreefire-api.squareweb.app"
PUBLIC_API_LAST_FETCH: Dict[str, float] = {}
PUBLIC_API_CACHE_SECONDS = 180


def _public_image_url(value, fallback_id=None):
    if isinstance(value, dict):
        value = value.get("webp") or value.get("jpeg") or value.get("png") or value.get("url")
    if isinstance(value, str) and value.strip():
        candidate = value.strip()
        if candidate.startswith("/"):
            candidate = f"{PUBLIC_FF_API}{candidate}"
        parsed = urlparse(candidate)
        if parsed.scheme == "https" and parsed.netloc == "hostfreefire-api.squareweb.app":
            return candidate
    if fallback_id is not None and str(fallback_id).isdigit():
        return f"{PUBLIC_FF_API}/api/iconsff?image={fallback_id}&format=webp"
    return None


async def _public_api_get(client, path, params):
    try:
        response = await client.get(f"{PUBLIC_FF_API}{path}", params=params)
        if response.status_code >= 400:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _sum_stat_modes(container, keys):
    total = 0
    for key in keys:
        block = container.get(key) if isinstance(container, dict) else None
        if not isinstance(block, dict):
            continue
        for field in ("games_played", "Games", "games"):
            if field in block:
                try:
                    total += int(block[field] or 0)
                except (TypeError, ValueError):
                    pass
                break
    return total


def _api_region(region: str) -> str:
    code = str(region or "BR").strip().upper()
    if code in {"BR", "SAC", "US", "NA", "LATAM", "BRAZIL"}:
        return "br"
    if code in {"IND", "IN", "INDIA"}:
        return "ind"
    if code in {"SG", "EU", "ME", "VN", "TW", "PK", "RU", "BD", "ID", "TH"}:
        return "sg"
    return "br"


async def refresh_public_player_data(account_id: str, region: str = "BR"):
    """Fetch only public profile/stat/ban data; never forwards Guest credentials."""
    account_id = str(account_id).strip()
    if not account_id.isdigit():
        return None
    region_code = _api_region(region)
    account = bot_state.accounts.get(account_id)
    if account is None:
        return None
    last_fetch = PUBLIC_API_LAST_FETCH.get(account_id, 0)
    if time.monotonic() - last_fetch < PUBLIC_API_CACHE_SECONDS and account.get("api_last_checked"):
        return account
    PUBLIC_API_LAST_FETCH[account_id] = time.monotonic()
    params = {"region": region_code}
    timeout = httpx.Timeout(9.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as api_client:
        profile, ban, br_stats, cs_stats = await asyncio.gather(
            _public_api_get(api_client, "/api/info_player", {"uid": account_id, **params, "clothes": "true"}),
            _public_api_get(api_client, "/api/check_banned", {"id": account_id, **params}),
            _public_api_get(api_client, "/api/stats", {"id": account_id, **params, "mode": "br"}),
            _public_api_get(api_client, "/api/stats", {"id": account_id, **params, "mode": "cs"}),
        )

    timestamp = time.strftime("%H:%M:%S")
    account.update({
        "api_last_checked": timestamp,
        "api_profile_status": "indisponível",
        "exp_check_status": "API indisponível",
        "exp_last_check": timestamp,
        "ban_status": "INDETERMINADO",
        "career_api_status": "indisponível",
    })

    if isinstance(profile, dict) and isinstance(profile.get("basicInfo"), dict):
        basic = profile["basicInfo"]
        profile_info = profile.get("profileInfo") or {}
        resolved = profile.get("resolved") or {}
        images = profile.get("images") or {}
        if not isinstance(profile_info, dict): profile_info = {}
        if not isinstance(resolved, dict): resolved = {}
        if not isinstance(images, dict): images = {}
        avatar_id = basic.get("headPic") or profile_info.get("avatarId")
        banner_id = basic.get("bannerId")
        outfit = images.get("outfit") or {}
        outfit_url = outfit.get("webp") or outfit.get("jpeg") if isinstance(outfit, dict) else None
        clothing = resolved.get("clothes") or []
        weapons = resolved.get("weaponSkinShows") or []
        skins = []
        if isinstance(clothing, list):
            skins.extend({"type": "Roupa", "name": str(item.get("name", "Item")), "id": str(item.get("id", "")),
                          "image_url": _public_image_url(None, item.get("id"))}
                         for item in clothing[:8] if isinstance(item, dict))
        if isinstance(weapons, list):
            skins.extend({"type": "Arma", "name": str(item.get("name", "Skin")), "id": str(item.get("id", "")),
                          "image_url": _public_image_url(None, item.get("id"))}
                         for item in weapons[:8] if isinstance(item, dict))
        account.update({
            "api_profile_status": "atualizado",
            "api_last_checked": timestamp,
            "avatar_url": _public_image_url(images.get("avatar"), avatar_id),
            "banner_url": _public_image_url(images.get("banner"), banner_id),
            "outfit_url": _public_image_url(outfit_url),
            "skins": skins,
            "profile_card_url": _public_image_url((images.get("profileCard") or {}).get("webp")) if isinstance(images.get("profileCard"), dict) else None,
        })
        try:
            exp = int(basic.get("exp", 0))
            level = int(basic.get("level", 0))
            if exp >= 0 and level > 0:
                bot_state.update_exp(account_id, exp, level)
                account.update({"exp_source": "API pública", "exp_check_status": "atualizado", "exp_last_check": timestamp})
            if basic.get("nickname"):
                account["nickname"] = str(basic["nickname"])
            if basic.get("liked") is not None:
                account["likes"] = int(basic["liked"] or 0)
        except (TypeError, ValueError):
            pass

    if isinstance(ban, dict):
        details = ban.get("details") or ban.get("banInfoData") or {}
        ban_value = str(details.get("is_banned", "")).strip().lower() if isinstance(details, dict) else ""
        if ban_value in {"yes", "true", "1", "banned"} or str(ban.get("status", "")).lower() == "banned":
            ban_status = "BANIDA"
        elif ban_value in {"no", "false", "0", "not banned"} or str(ban.get("msg", "")).lower() == "account_not_banned":
            ban_status = "SEM BANIMENTO"
        else:
            ban_status = "INDETERMINADO"
        account.update({
            "ban_status": ban_status,
            "ban_reason": details.get("banReason") if isinstance(details, dict) else None,
            "ban_period": details.get("banned_period") if isinstance(details, dict) else None,
            "ban_checked_at": timestamp,
        })
    else:
        account.update({"ban_status": "INDISPONÍVEL", "ban_checked_at": timestamp})

    if isinstance(br_stats, dict) and not br_stats.get("error"):
        br_career = br_stats.get("BR_CAREER") or {}
        if isinstance(br_career, dict):
            keys = ("solo_stats", "duo_stats", "squad_stats")
            account["career_br_matches"] = _sum_stat_modes(br_career, keys)
            for output_key, source_key in (("career_br_wins", "wins"), ("career_br_kills", "kills")):
                total = 0
                for mode_key in keys:
                    mode_data = br_career.get(mode_key)
                    if isinstance(mode_data, dict):
                        try:
                            total += int(mode_data.get(source_key, 0) or 0)
                        except (TypeError, ValueError):
                            pass
                account[output_key] = total
    cs_results = cs_stats.get("results", {}) if isinstance(cs_stats, dict) else {}
    if isinstance(cs_results, dict):
        cs_career = cs_results.get("cs_career") or {}
        if isinstance(cs_career, dict):
            try:
                account["career_cs_matches"] = int(cs_career.get("Games", cs_career.get("gamesPlayed", 0)) or 0)
                account["career_cs_wins"] = int(cs_career.get("Wins", cs_career.get("wins", 0)) or 0)
            except (TypeError, ValueError):
                pass

    stats_ok = (isinstance(br_stats, dict) and "BR_CAREER" in br_stats) or (isinstance(cs_stats, dict) and isinstance(cs_stats.get("results"), dict))
    account["career_api_status"] = "atualizado" if stats_ok else "indisponível"
    bot_state.recalc_totals()
    bot_state.log(f"API pública atualizada: ban={account.get('ban_status')}, perfil={'OK' if account.get('api_profile_status') == 'atualizado' else 'indisponível'}", "info", account_id)
    return account


async def process_account_credentials(uid: str, auth_type: str, password: str = "", access_token: str = "") -> Optional[Dict]:
    log(f"[*] Logging in UID: {uid} ({auth_type})")
    try:
        async with _LOGIN_SEMAPHORE:
            verconfig_res = await version_config()
            if verconfig_res is None:
                return None
            release_version, client_version, server_url = verconfig_res

            if auth_type == "access_token":
                token_data = await _public_api_get(client, "/api/v1/token", {"access_token": access_token, "token_type": "game"})
                token_info = token_data.get("tokenBasicInfo") if isinstance(token_data, dict) else None
                if not isinstance(token_info, dict):
                    log(f"[-] Access Token invalid or unsupported for UID {uid}")
                    return None
                open_id = token_info.get("open_id")
                platform = token_info.get("platform", 4)
                access_token_value = access_token
                resolved_uid = str(token_info.get("uid") or uid)
            else:
                tokengrant_response = await get_access_token(uid, password)
                if tokengrant_response is None:
                    log(f"[-] OAuth failed for UID {uid}")
                    return None
                open_id, access_token_value, platform = tokengrant_response
                resolved_uid = str(uid)

            if not open_id or not access_token_value:
                return None
            device_info = get_device_for_account(resolved_uid)
            login_payload_data = await build_majorlogin_payload(open_id, access_token_value, platform, client_version, device_info)
            if login_payload_data is None:
                return None

            majorlogin_response = await send_majorlogin(login_payload_data, release_version, server_url)
            if majorlogin_response is None:
                log(f"[-] MajorLogin failed for {resolved_uid}")
                return None

            getlogin_result = await send_getlogin(
                login_payload_data,
                majorlogin_response.url,
                majorlogin_response.token,
                release_version
            )
            if getlogin_result is None:
                log(f"[-] GetLoginData failed for {resolved_uid}")
                return None

            res_proto, dict_res = getlogin_result

        acc_id = str(majorlogin_response.account_id)
        if acc_id == "0" or not acc_id or acc_id == "None":
            log(f"[-] Invalid account_id (0) for UID {resolved_uid} — skipping this account")
            return None

        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, "BR")
        level = max(1, level)
        exp = max(0, exp)

        func_addr = res_proto.functional_addrs
        info_addr = res_proto.informational_addrs
        if not isinstance(func_addr, str) or not func_addr or ":" not in func_addr:
            func_addr = None
        if not isinstance(info_addr, str) or not info_addr or ":" not in info_addr:
            info_addr = None

        key_val = majorlogin_response.aes_ak
        iv_val = majorlogin_response.iv_i
        if not isinstance(key_val, (bytes, bytearray)) or len(key_val) < 16:
            key_val = AES_KEY
        if not isinstance(iv_val, (bytes, bytearray)) or len(iv_val) < 16:
            iv_val = AES_IV

        log(f"[+] Login OK | UID {acc_id} | {nickname} | Lvl {level} | Região: {region} | modo da squad definido no painel")
        return {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'level': level,
            'exp': exp,
            'open_id': open_id,
            'access_token': access_token_value,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': key_val,
            'iv_i': iv_val,
            'functional_addrs': func_addr,
            'informational_addrs': info_addr,
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': auth_type,
            'auth_uid': uid,
            'auth_password': password,
            'auth_access_token': access_token if auth_type == "access_token" else ""
        }
    except Exception as e:
        log(f"[-] process_account_credentials error ({type(e).__name__}) for UID {uid}")
        return None


async def process_account_uid_pass(uid: str, password: str) -> Optional[Dict]:
    return await process_account_credentials(str(uid), "guest", password=str(password))


async def process_account_access_token(uid: str, access_token: str) -> Optional[Dict]:
    return await process_account_credentials(str(uid), "access_token", access_token=str(access_token))


async def run_account_worker(account_data: Dict, label: str):
    acc_id = str(account_data['account_id'])
    informational_task = None
    exp_task = None
    functional_task = None
    try:
        reg = account_data.get('region', 'ME')
        func_addr = account_data.get('functional_addrs')
        info_addr = account_data.get('informational_addrs')

        if not func_addr or not isinstance(func_addr, str) or ":" not in func_addr:
            print_warning(f"[!] No functional_addrs for {acc_id} — worker idle")
            while True:
                await asyncio.sleep(60)
            return

        tcp_packet_online = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='OnLine'
        )

        tcp_packet_chat = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='ChaT'
        )

        if info_addr and isinstance(info_addr, str) and ":" in info_addr:
            informational_task = asyncio.create_task(
                informational(
                    info_addr,
                    tcp_packet_chat,
                    account_data['aes_ak'],
                    account_data['iv_i'],
                    region=reg,
                    account_id=acc_id
                )
            )

        async def exp_refresher():
            while True:
                await asyncio.sleep(120 + random.uniform(-10.0, 10.0))
                try:
                    await refresh_account_profile(account_data)
                except Exception:
                    pass

        exp_task = asyncio.create_task(exp_refresher())

        functional_task = asyncio.create_task(
            functional_br(
                func_addr,
                tcp_packet_online,
                account_data['region'],
                account_data['client_version'],
                account_data['aes_ak'],
                account_data['iv_i'],
                account_id=acc_id,
                account_data=account_data
            )
        )

        await functional_task

    except asyncio.CancelledError:
        raise
    except Exception as e:
        print_error(f"run_account_worker error for {label}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        for t in (informational_task, exp_task, functional_task):
            if t and not t.done():
                t.cancel()
        for t in (informational_task, exp_task, functional_task):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass


async def account_loop_auth(auth_type: str, uid: str, password: str = "", access_token: str = ""):
    uid_str = str(uid)
    dashboard_uid = str(bot_state.account_credentials.get(uid_str, uid_str))
    while True:
        try:
            log(f"[*] Starting {auth_type} login for UID: {uid_str}")
            if dashboard_uid not in bot_state.accounts:
                bot_state.accounts[dashboard_uid] = {
                    "uid": dashboard_uid, "nickname": f"Guest_{uid_str[-6:]}", "region": "BR",
                    "level": 1, "initial_exp": 0, "current_exp": 0, "gained_exp": 0,
                    "likes": 0, "status": "CONNECTING", "matches_played": 0,
                    "active_matches": 0, "last_match_time": None,
                    "last_updated": time.strftime("%H:%M:%S"), "profile_initialized": False,
                    "ban_status": "PENDENTE", "api_profile_status": "PENDENTE",
                    "exp_check_status": "PENDENTE", "skins": []
                }
            bot_state.update_status(dashboard_uid, "CONNECTING")
            if auth_type == "access_token":
                account_data = await process_account_access_token(uid_str, access_token)
            else:
                account_data = await process_account_uid_pass(uid_str, password)
            if not account_data:
                log(f"[-] Login failed for {uid_str}. Retry in 15s...")
                bot_state.update_status(dashboard_uid, "ERROR")
                await asyncio.sleep(15)
                continue
            actual_uid = str(account_data['account_id'])
            if actual_uid != uid_str and uid_str in bot_state.accounts:
                bot_state.accounts.pop(uid_str, None)
            dashboard_uid = actual_uid
            bot_state.account_credentials[uid_str] = dashboard_uid
            bot_state.register_account(
                uid=dashboard_uid,
                nickname=account_data.get('nickname', f"Player_{account_data['account_id']}"),
                region=account_data.get('region', 'BR'),
                level=int(account_data.get('level', 1)),
                exp=int(account_data.get('exp', 0)),
                likes=int(account_data.get('likes', 0))
            )
            account_data["dashboard_uid"] = dashboard_uid
            await refresh_public_player_data(dashboard_uid, account_data.get('region', 'BR'))
            if bot_state.accounts.get(dashboard_uid, {}).get("ban_status") == "BANIDA":
                bot_state.update_status(dashboard_uid, "BANIDA")
                log(f"[!] A consulta pública sinalizou banimento para {dashboard_uid}; worker pausado")
                await asyncio.sleep(300)
                continue
            bot_state.update_status(dashboard_uid, "ONLINE")
            await run_account_worker(account_data, uid_str)
            log(f"[!] Session ended for {uid_str}. Reconnecting in 3s...")
            bot_state.update_status(dashboard_uid, "OFFLINE")
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            log(f"[!] Worker stopped for {uid_str}")
            bot_state.update_status(dashboard_uid, "OFFLINE")
            break
        except Exception as e:
            log(f"[-] Error for UID {uid_str}: {e}. Retry in 10s...")
            bot_state.update_status(dashboard_uid, "ERROR")
            await asyncio.sleep(10)


async def account_loop_guest(uid: str, password: str):
    await account_loop_auth("guest", uid, password=password)


async def account_loop_access_token(uid: str, access_token: str):
    await account_loop_auth("access_token", uid, access_token=access_token)

def load_accounts():
    accounts_path = ACCOUNTS_PATH
    try:
        with open(accounts_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("accounts.json precisa conter uma lista")
        return [item for item in data if isinstance(item, dict) and item.get("uid") and
                ((item.get("auth_type", "guest") == "guest" and item.get("password")) or
                 (item.get("auth_type") == "access_token" and item.get("access_token")))]
    except FileNotFoundError:
        return []
    except Exception as e:
        log(f"[-] Não foi possível carregar accounts.json: {e}")
        return []


def start_guest_worker(uid: str, password: str):
    uid = str(uid).strip()
    current = bot_state.account_workers.get(uid)
    if current and not current.done():
        return current
    task = asyncio.create_task(account_loop_guest(uid, password))
    bot_state.account_workers[uid] = task
    return task


def start_access_token_worker(uid: str, access_token: str):
    uid = str(uid).strip()
    current = bot_state.account_workers.get(uid)
    if current and not current.done():
        return current
    task = asyncio.create_task(account_loop_access_token(uid, access_token))
    bot_state.account_workers[uid] = task
    return task


async def main():
    print("=" * 60)
    print("    LADY GLORY - Free Fire Account Monitor")
    print("   Persistent Device ID + TRUE Parallel + Smart DNS")
    print("=" * 60)
    print("[i] Matchmaking individual: desativado; fila somente após Squad 4/4")
    print(f"[i] Offline Wait: 3.0s (after match found)")
    print(f"[i] Non-match Reconnect: {NON_MATCH_RECONNECT_DELAY}s")
    print(f"[i] Cache Invalidation Threshold: 5.0x")
    print(f"[i] Parallel Matches: UNLIMITED (background)")
    print(f"[i] Cache TTL: 1200s (20 min)")
    print(f"[i] Priority Regions: ['BD', 'IND', 'SG', 'TH', 'PH', 'VN', 'MY', 'ID', 'HK', 'TW']")
    print("[i] Device System: 1 ID = 1 Persistent Device ID (devices.json)")
    print("=" * 60)

    # Render define PORT; fora dele, manter o painel local por padrão.
    dashboard_port = int(os.environ.get("PORT", "20335"))
    dashboard_host = os.environ.get("DASHBOARD_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    await start_web_dashboard(host=dashboard_host, port=dashboard_port)
    bot_state.refresh_callbacks["on_account_added"] = lambda data: _on_account_added(data)
    bot_state.refresh_callbacks["on_refresh_account"] = lambda uid: _on_refresh_account(uid)
    bot_state.refresh_callbacks["on_squad_start"] = lambda members, mode: _on_squad_start(members, mode)
    log(f"[+] Lady Glory iniciado. Dashboard escutando em {dashboard_host}:{dashboard_port}")

    accounts = load_accounts()
    for acc in accounts:
        if acc.get("auth_type") == "access_token":
            start_access_token_worker(str(acc["uid"]), str(acc["access_token"]))
        else:
            start_guest_worker(str(acc["uid"]), str(acc["password"]))
    if not accounts:
        log("[i] Nenhuma conta carregada. Adicione uma conta Guest ou Access Token pelo painel local.")

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        raise
    finally:
        workers = list(bot_state.account_workers.values())
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        log("[+] Workers encerrados.")


async def _on_account_added(data):
    uid = str(data.get("uid", "")).strip()
    password = str(data.get("password", "")).strip()
    auth_type = str(data.get("auth_type", "guest")).strip().lower()
    if uid and auth_type == "access_token" and data.get("access_token"):
        current = bot_state.account_workers.get(uid)
        if current and not current.done():
            current.cancel()
            await asyncio.gather(current, return_exceptions=True)
        start_access_token_worker(uid, str(data["access_token"]))
        bot_state.log(f"Worker Access Token iniciado para UID {uid}", "success", uid)
    elif uid and password:
        current = bot_state.account_workers.get(uid)
        if current and not current.done():
            current.cancel()
            await asyncio.gather(current, return_exceptions=True)
        start_guest_worker(uid, password)
        bot_state.log(f"Worker Guest iniciado para UID {uid}", "success", uid)


async def _on_refresh_account(uid: str):
    account_id = str(uid).strip()
    account = bot_state.accounts.get(account_id)
    if account:
        await refresh_public_player_data(account_id, account.get("region", "BR"))


async def _on_squad_start(members: List[str], mode: str = "CS"):
    members = [str(uid).strip() for uid in members]
    if len(members) != 4 or len(set(members)) != 4 or any(not uid.isdigit() for uid in members):
        return {"status": "error", "error": "A squad precisa de quatro UIDs distintos."}
    mode = str(mode or "CS").upper()
    if mode not in {"BR", "CS"}:
        return {"status": "error", "error": "Modo inválido; use BR ou CS."}
    for uid in members:
        account = bot_state.accounts.get(uid)
        if not account:
            return {"status": "error", "error": f"A conta {uid} ainda não apareceu na Main."}
        if str(account.get("status", "")).upper() not in {"ONLINE", "IN_MATCH"}:
            return {"status": "error", "error": f"A conta {uid} não está online (status: {account.get('status', '—')})."}
    result = await squad_coordinator.activate(members, mode)
    if result.get("status") == "ok":
        bot_state.log(f"Solicitação manual de squad {mode} recebida; aguardando as quatro sessões.", "info", members[0])
    return result


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
