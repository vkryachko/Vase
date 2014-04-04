

from vase import Vase
from vase.sockjs import forbid_websocket

app = Vase(__name__)


@app.endpoint(path="/echo")
class EchoEndpoint:
    """
    WebSocket endpoint
    Has the following attributes:
    `bag` - a dictionary that is shared between all instances of this endpoint
    `transport` - used to send messages into the websocket
    """
    def on_connect(self):
        print("Successfully connected")

    def on_message(self, message):
        print("on_message", self)
        self.transport.send(message)

    def on_close(self, exc=None):
        print("Connection closed")


@app.endpoint(path="/disabled_websocket_echo")
@forbid_websocket
class EchoEndpoint:
    """
    WebSocket endpoint
    Has the following attributes:
    `bag` - a dictionary that is shared between all instances of this endpoint
    `transport` - used to send messages into the websocket
    """
    def on_connect(self):
        print("Successfully connected")

    def on_message(self, message):
        self.transport.send(message)

    def on_close(self, exc=None):
        print("Connection closed")


@app.endpoint(path="/close")
class EchoEndpoint:
    """
    WebSocket endpoint
    Has the following attributes:
    `bag` - a dictionary that is shared between all instances of this endpoint
    `transport` - used to send messages into the websocket
    """
    def on_connect(self):
        print("Connected")
        self.transport.close()

    def on_message(self, message):
        pass

    def on_close(self, exc=None):
        pass


if __name__ == '__main__':
    app.run()
