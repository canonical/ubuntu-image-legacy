#!/usr/bin/python3

import asyncio

from syslog import syslog


syslog('Starting echo service')


class EchoServerClientProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        syslog('Connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, data):
        try:
            message = data.decode()
            syslog('Data received: {!r}'.format(message))
            syslog('Send: {!r}'.format(message))
            self.transport.write(data.swapcase())
        except Exception as error:
            syslog(str(error))


def main():
    loop = asyncio.get_event_loop()
    # Each client connection will create a new protocol instance.  Listen on
    # all IP addresses.
    coro = loop.create_server(EchoServerClientProtocol, '', 8888)
    server = loop.run_until_complete(coro)

    # Serve requests until Ctrl+C is pressed
    syslog('Serving on {}'.format(server.sockets[0].getsockname()))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    # Close the server
    try:
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()
    except Exception as error:
        syslog(str(error))


if __name__ == '__main__':
    main()
