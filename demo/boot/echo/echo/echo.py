#!/usr/bin/python3

import asyncio


print('Starting echo service')


class EchoServerClientProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        print('Connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, data):
        message = data.decode()
        print('Data received: {!r}'.format(message))
        print('Send: {!r}'.format(message))
        self.transport.write(data.swapcase())


def main():
    loop = asyncio.get_event_loop()
    # Each client connection will create a new protocol instance.  Listen on
    # all IP addresses.
    coro = loop.create_server(EchoServerClientProtocol, '', 8888)
    server = loop.run_until_complete(coro)

    # Serve requests until Ctrl+C is pressed
    print('Serving on {}'.format(server.sockets[0].getsockname()))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    # Close the server
    try:
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()
    except Exception:
        pass


if __name__ == '__main__':
    main()
