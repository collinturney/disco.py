#!/usr/bin/env python3

import argparse
import logging
import logging.handlers
import os
import platform
import select
import socket
import sys
import time


class Disco(object):

    LOG_DEVICE = "/dev/log"
    HOST = "<broadcast>"
    PORT = 9000
    DELAY = 15

    def __init__(self, debug=False):
        self.log = logging.getLogger("Disco")
        self.log.addHandler(logging.StreamHandler(sys.stdout))

        if os.path.exists(self.LOG_DEVICE):
            self.log.addHandler(logging.handlers.SysLogHandler(address=self.LOG_DEVICE))

        if debug:
            self.log.setLevel(logging.DEBUG)
        else:
            self.log.setLevel(logging.INFO)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setblocking(0)

    def listen(self, port, timeout=None):
        self.log.info(f"Listening on port {port}...")
        self.sock.bind(("", port))
        hosts = {}
        start = time.time()
        while True:
            ready = select.select([self.sock], [], [], 1)

            if ready[0]:
                msg, addr = self.sock.recvfrom(1024)
                hosts[addr[0]] = msg.decode()
                self.log.info(f"Received {addr[0]} : {msg.decode()}")
            else:
                self.log.debug("No hosts")

            if timeout and time.time() - start >= timeout:
                return hosts

    def broadcast(self, host, port, delay):
        self.log.info(f"Broadcasting to {host}:{port}...")
        while True:
            msg = f"HOST {platform.node()} {int(time.time())}"
            self.log.debug(f"Sending '{msg}' -> {host}:{port}")
            self.sock.sendto(msg.encode(), (host, port))
            time.sleep(delay)


def configure():
    parser = argparse.ArgumentParser(description="disco.py - Host discovery tool")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--listen", "-l", default=False, action="store_true", help="Listen mode")
    mode.add_argument("--broadcast", "-b", default=False, action="store_true", help="Broadcast mode")

    parser.add_argument("--host", default=Disco.HOST, help="Target host (default: UDP broadcast)")
    parser.add_argument("--port", default=Disco.PORT, type=int, help="Target port (default: 9000)")
    parser.add_argument("--delay", default=Disco.DELAY, type=int, help="Broadcast delay in seconds (default: 15)")
    parser.add_argument("--debug", default=False, action="store_true", help="Enable debug output")

    return parser.parse_args()


def main():
    args = configure()

    try:
        disco = Disco(args.debug)

        if args.broadcast:
            disco.broadcast(args.host, args.port, args.delay)
        elif args.listen:
            hosts = disco.listen(args.port)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    ret = main()
    sys.exit(ret)
