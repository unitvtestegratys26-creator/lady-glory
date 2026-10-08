import asyncio
import unittest

from gateway_framing import read_gateway_frame


class GatewayFramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_concatenated_frames_one_at_a_time(self):
        first = bytes.fromhex("d50000000171")
        second = bytes.fromhex("050000000401020304")
        reader = asyncio.StreamReader()
        reader.feed_data(first + second)
        buffer = bytearray()

        self.assertEqual(await read_gateway_frame(reader, buffer), first)
        self.assertEqual(await read_gateway_frame(reader, buffer), second)
        self.assertEqual(buffer, bytearray())

    async def test_reassembles_a_fragmented_frame(self):
        frame = bytes.fromhex("050000000401020304")
        reader = asyncio.StreamReader()
        buffer = bytearray()
        task = asyncio.create_task(read_gateway_frame(reader, buffer))
        reader.feed_data(frame[:3])
        await asyncio.sleep(0)
        reader.feed_data(frame[3:])

        self.assertEqual(await asyncio.wait_for(task, timeout=1), frame)

    async def test_zero_payload_frame(self):
        frame = bytes.fromhex("d500000000")
        reader = asyncio.StreamReader()
        reader.feed_data(frame)

        self.assertEqual(await read_gateway_frame(reader, bytearray()), frame)


if __name__ == "__main__":
    unittest.main()
