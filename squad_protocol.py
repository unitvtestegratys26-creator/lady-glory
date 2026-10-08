"""Helpers mínimos de protocolo de squad usados pela Main Lady Glory.

Este módulo cria salas BR/CS, envia convites individuais e aceita convites do
líder selecionado. Não contém loops de envio, comandos de amizade, emotes ou
mensagens de chat.
"""
from __future__ import annotations

import re
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def _varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        value = (1 << 64) + value
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _length_delimited(field_no: int, value: bytes) -> bytes:
    return _varint((field_no << 3) | 2) + _varint(len(value)) + value


def _protobuf(fields: dict[int, Any]) -> bytes:
    out = bytearray()
    for field_no, value in fields.items():
        if isinstance(value, dict):
            out.extend(_length_delimited(int(field_no), _protobuf(value)))
        elif isinstance(value, bool):
            out.extend(_varint((int(field_no) << 3) | 0) + _varint(int(value)))
        elif isinstance(value, int):
            out.extend(_varint((int(field_no) << 3) | 0) + _varint(value))
        elif isinstance(value, str):
            data = value.encode("utf-8")
            out.extend(_length_delimited(int(field_no), data))
        elif isinstance(value, (bytes, bytearray)):
            out.extend(_length_delimited(int(field_no), bytes(value)))
        else:
            raise TypeError(f"Unsupported protobuf value: {type(value).__name__}")
    return bytes(out)


def _hex_bytes_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _hex_bytes_recursive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_hex_bytes_recursive(item) for item in value]
    if isinstance(value, str) and len(value) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", value):
        try:
            return bytes.fromhex(value)
        except ValueError:
            return value
    return value


def _packet_type(region: str) -> str:
    region = str(region or "ME").upper()
    if region == "IND":
        return "0514"
    if region == "BD":
        return "0519"
    return "0515"


def _encrypt_game_packet(fields: dict[int, Any], packet_type: str, key: bytes, iv: bytes) -> bytes:
    key, iv = bytes(key), bytes(iv)
    if len(key) not in (16, 24, 32) or len(iv) != 16:
        raise ValueError("AES key/IV inválidos para pacote squad")
    payload = _protobuf(_hex_bytes_recursive(fields))
    encrypted = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(payload, AES.block_size))
    size_hex = f"{len(encrypted):x}"
    if len(size_hex) == 2:
        size_prefix = "000000"
    elif len(size_hex) == 3:
        size_prefix = "00000"
    elif len(size_hex) == 4:
        size_prefix = "0000"
    else:
        size_prefix = "000"
    return bytes.fromhex(packet_type + size_prefix + size_hex + encrypted.hex())


def build_create_br_squad(key: bytes, iv: bytes, region: str = "ME", client_version: str = "") -> bytes:
    """Build one BR-squad creation packet based on the supplied OB54 sample."""
    version = str(client_version or "1.127.1")[:32]
    game_region = str(region or "ME").upper()
    fields = {
        1: 1,
        2: {
            2: "01161d",
            3: 5,
            4: 5,
            5: "ar",
            8: {1: "IDC3", 2: 133, 3: game_region},
            9: 5,
            10: "01030407090a0b1216191a201d27",
            11: 1,
            13: 1,
            # The source sample's indentation omitted field 14 on its BR branch;
            # keep these client/version fields nested consistently with its CS branch.
            14: {
                1: {5: 56},
                2: 354,
                4: "7f585855",
                6: 11,
                7: "16777b7f6b6e1214",
                8: version,
                9: 5,
                10: 5,
            },
            19: 329,
            21: "374f5219",
            24: {1: 21},
        },
    }
    return _encrypt_game_packet(fields, _packet_type(game_region), key, iv)


def build_create_cs_squad(key: bytes, iv: bytes, region: str = "ME", client_version: str = "") -> bytes:
    """Build a Clash Squad lobby packet from OB54's _get_squad_fields('CS')."""
    version = str(client_version or "1.127.1")[:32]
    game_region = str(region or "ME").upper()
    fields = {
        1: 1,
        2: {
            2: "010304161d",
            3: 15,
            4: 3,
            5: "ar",
            8: {1: "IDC3", 2: 132, 3: game_region},
            9: 6,
            10: "01030407090a0b1216191a201d27",
            11: 1,
            13: 1,
            14: {
                1: {6: 56},
                2: 250,
                4: "7f585855",
                6: 11,
                7: "16777b7f6b6e1214",
                8: version,
                9: 3,
                10: 2,
            },
            19: 324,
            20: 36,
            21: "374f5219",
            24: {1: 21},
        },
    }
    return _encrypt_game_packet(fields, _packet_type(game_region), key, iv)


def build_create_squad(mode: str, key: bytes, iv: bytes, region: str = "ME",
                       client_version: str = "") -> bytes:
    mode = str(mode or "CS").upper()
    if mode == "CS":
        return build_create_cs_squad(key, iv, region, client_version)
    if mode == "BR":
        return build_create_br_squad(key, iv, region, client_version)
    raise ValueError("Modo de squad inválido; use BR ou CS")


def build_squad_chat_auth(owner_uid: str, key: bytes, iv: bytes, code: str = "0") -> bytes:
    """Authenticate the leader in squad chat using OB54's xC4 AutH_Chat."""
    if not str(owner_uid).isdigit():
        raise ValueError("UID do líder inválido para autenticação de chat")
    fields = {1: 3, 2: {1: int(owner_uid), 3: "en", 4: str(code)}}
    return _encrypt_game_packet(fields, "1215", key, iv)


def build_invite(target_uid: str, key: bytes, iv: bytes, region: str = "ME") -> bytes:
    if not str(target_uid).isdigit():
        raise ValueError("UID convidado inválido")
    fields = {1: 2, 2: {1: int(target_uid), 2: str(region or "ME"), 4: 5}}
    return _encrypt_game_packet(fields, _packet_type(region), key, iv)


def build_accept_invite(owner_uid: str, invite_code: Any, key: bytes, iv: bytes,
                        region: str = "ME", client_version: str = "") -> bytes:
    if not str(owner_uid).isdigit():
        raise ValueError("UID do líder inválido")
    version = str(client_version or "1.127.1")[:32]
    fields = {
        1: 4,
        2: {
            1: int(owner_uid),
            3: int(owner_uid),
            4: bytes.fromhex("01090a0b121920"),
            8: 1,
            9: {
                2: 161,
                4: "y[WW",
                6: 11,
                8: version,
                9: 3,
                10: 1,
            },
            10: str(invite_code),
        },
    }
    return _encrypt_game_packet(fields, _packet_type(region), key, iv)


def build_status_request(player_uid: str, key: bytes, iv: bytes) -> bytes:
    """Request the player's own lobby/squad status using the OB54 0F15 query."""
    if not str(player_uid).isdigit():
        raise ValueError("UID consultado inválido")
    uid_bytes = _varint(int(player_uid))
    return _encrypt_game_packet(
        {1: 1, 2: {1: uid_bytes, 2: 5}}, "0F15", key, iv
    )
