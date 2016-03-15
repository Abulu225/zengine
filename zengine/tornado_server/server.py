# -*-  coding: utf-8 -*-
"""
tornado websocket proxy for WF worker daemons
"""
# Copyright (C) 2015 ZetaOps Inc.
#
# This file is licensed under the GNU General Public License v3
# (GPLv3).  See LICENSE.txt for details.
import json
import os, sys
import traceback
from uuid import uuid4
from tornado import websocket, web, ioloop
from tornado.escape import json_decode, json_encode
from tornado.httpclient import HTTPError

sys.path.insert(0, os.path.realpath(os.path.dirname(__file__)))
from queue_manager import QueueManager, BlockingConnectionForHTTP, log


COOKIE_NAME = 'zopsess'
DEBUG = os.getenv("DEBUG", False)
blocking_connection = BlockingConnectionForHTTP()

class SocketHandler(websocket.WebSocketHandler):
    """
    websocket handler
    """

    def check_origin(self, origin):
        """
        Prevents CORS attacks.

        Args:
            origin: HTTP "Origin" header. URL of initiator of the request.

        Returns:
            True if origin is legit, otherwise False
        """
        # FIXME: implement CORS checking
        return True

    def _get_sess_id(self):
        # return self.sess_id;
        sess_id = self.get_cookie(COOKIE_NAME)
        return sess_id

    def open(self):
        """
        Called on new websocket connection.
        """
        sess_id = self._get_sess_id()
        if sess_id:
            self.application.pc.register_websocket(self._get_sess_id(), self)
        else:
            self.write_message(json.dumps({"error": "Please login", "code": 401}))

    def on_message(self, message):
        """
        called on new websocket message,
        """
        self.application.pc.redirect_incoming_message(self._get_sess_id(), message)

    def on_close(self):
        """
        remove connection from pool on connection close.
        """
        self.application.pc.unregister_websocket(self._get_sess_id())


class HttpHandler(web.RequestHandler):
    """
    login handler class
    """


    @web.asynchronous
    def get(self, view_name):
        self.post(view_name)

    @web.asynchronous
    def post(self, view_name):
        """
        login handler
        """
        try:
            self.set_header('Access-Control-Allow-Origin', self.request.headers.get('Origin'))
            self.set_header('Access-Control-Allow-Credentials', 'true')
            self.set_header('Content-Type', 'application/json')
            if not self.get_cookie(COOKIE_NAME):
                sess_id = uuid4().hex
                self.set_cookie(COOKIE_NAME, sess_id)  # , domain='127.0.0.1'
            else:
                sess_id = self.get_cookie(COOKIE_NAME)
            h_sess_id = "HTTP_%s" % sess_id
            input_data = json_decode(self.request.body) if self.request.body else {}
            input_data['path'] = view_name
            input_data = {'data': input_data}
            input_data['callbackID'] = uuid4().hex
            log.info("new request: %s" % input_data)

            self.application.pc.redirect_incoming_message(h_sess_id, json_encode(input_data))
            response = blocking_connection.wait_for_message(h_sess_id, input_data['callbackID'])
            output = response
            self.set_status(int(json_decode(output).get('code', 200)))
        except HTTPError as e:
            output = {'error': e.message, "code": e.code}
            self.set_status(int(e.code))
        except:
            if DEBUG:
                self.set_status(500)
                output = json.dumps({'error': traceback.format_exc()})
            else:
                output = {'error': "Internal Error", "code": 500}
        self.write(output)
        self.finish()
        self.flush()


URL_CONFS = [
    (r'/ws', SocketHandler),
    (r'/(\w+)', HttpHandler),
]

app = web.Application(URL_CONFS, debug=DEBUG)


def runserver(host=None, port=None):
    """
    Run Tornado server
    """
    host = host or os.getenv('HTTP_HOST', '0.0.0.0')
    port = port or os.getenv('HTTP_PORT', '9001')
    zioloop = ioloop.IOLoop.instance()

    # setup pika client:
    pc = QueueManager(zioloop)
    app.pc = pc
    pc.connect()
    app.listen(port, host)
    zioloop.start()


if __name__ == '__main__':
    runserver()