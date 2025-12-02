import asyncio
import unittest
from multiprocessing import Process
import time
import websockets

from sockjstest.sockjs import app


class SockjsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)
        self.server_process = Process(target=app.run, kwargs={'host': '127.0.0.1', 'port': 8080})
        self.server_process.start()
        time.sleep(1)

    def tearDown(self):
        self.server_process.terminate()
        self.server_process.join()
        self.loop.close()

    def test_echo(self):
        async def echo():
            uri = "ws://127.0.0.1:8080/echo/websocket"
            async with websockets.connect(uri) as websocket:
                await websocket.send("Hello world!")
                response = await websocket.recv()
                self.assertEqual(response, "Hello world!")

        self.loop.run_until_complete(echo())
