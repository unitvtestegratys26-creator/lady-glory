"""Framing TCP do gateway Free Fire: packet id (2 bytes), tamanho (3 bytes), payload."""
from __future__ import annotations

import asyncio

HEADER_SIZE = 5
MAX_PAYLOAD_SIZE = 2 * 1024 * 1024


async def read_gateway_frame(reader, buffer: bytearray) -> bytes:
    """Retorna um frame completo; preserva frames subsequentes e leituras parciais.

    TCP é um fluxo, não uma sequência de mensagens: um ``read`` pode retornar parte
    de um frame ou vários frames concatenados. O cabeçalho recebido observado nos
    logs usa dois bytes de ID e três bytes de tamanho em big-endian.
    """
    while True:
        if len(buffer) >= HEADER_SIZE:
            payload_size = int.from_bytes(buffer[2:HEADER_SIZE], "big")
            if payload_size > MAX_PAYLOAD_SIZE:
                raise ValueError(f"Tamanho de frame inválido no gateway: {payload_size}")
            frame_size = HEADER_SIZE + payload_size
            if len(buffer) >= frame_size:
                frame = bytes(buffer[:frame_size])
                del buffer[:frame_size]
                return frame

        chunk = await reader.read(65535)
        if not chunk:
            if buffer:
                raise ConnectionError(f"Conexão encerrada com frame incompleto ({len(buffer)} bytes)")
            return b""
        buffer.extend(chunk)
