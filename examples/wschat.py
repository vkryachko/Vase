from vase import Vase
import asyncio
import os.path
from datetime import datetime
import html
from vase.response import HttpResponse

app = Vase(__name__)

html_body = open(os.path.join(os.path.dirname(__file__), 'main.html'), 'r').read()

@app.route(path="/")
def hello(request):
    return html_body

@app.endpoint(path="/ws/chat")
class Endpoint:
    def authorize_request(self, environ):
        self.username = environ['QUERY_STRING'];
        return True

    def on_connect(self):
        if 'users' not in self.bag:
            self.bag['users'] = {}

        users = self.bag['users']

        users[self.username] = self.transport

        self.broadcast("User '{}' entered chat".format(self.username))

    def on_message(self, message):
        if isinstance(message, bytes):
            message = message.decode('utf-8')

        now = datetime.now().strftime("%H:%M:%S")
        msg = "[{}] {}: {}".format(now, self.username, html.escape(message))
        self.broadcast(msg)

    def broadcast(self, message):
        for username, transport in self.bag['users'].items():
            transport.send(message)


    def on_close(self, exc=None):
        users = self.bag['users']
        del users[self.username]
        print('closed')

if __name__ == '__main__':
    app.run()
