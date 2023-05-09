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
import zmq
from zmq.devices import ThreadProxy


class Disco(object):
    """Disco base class for constants, logging, and socket creation."""

    LOG_DEVICE = "/dev/log"
    IPC_PATH = "ipc:///var/tmp/disco"
    BROADCAST = "<broadcast>"
    PORT = 9000
    DELAY = 15

    def __init__(self, debug=False):
        """Create a Disco logger and avoid duplicate handlers."""
        self.log = logging.getLogger("Disco")

        if not self.log.hasHandlers():
            self.log.addHandler(logging.StreamHandler(sys.stdout))

        if os.path.exists(self.LOG_DEVICE):
            self.log.addHandler(logging.handlers.SysLogHandler(address=self.LOG_DEVICE))

        if debug:
            self.log.setLevel(logging.DEBUG)
        else:
            self.log.setLevel(logging.INFO)

    @staticmethod
    def udp_socket():
        """Returns a socket configured for UDP broadcasts."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(0)
        return sock


class BroadcastServer(Disco):
    """Broadcast UDP host discovery packets."""

    def __init__(self, debug: bool = False):
        """Create UDP broadcast socket and create a local metrics proxy."""
        super().__init__(debug)
        self.sock = Disco.udp_socket()
        self.proxy = MetricsProxy()

    def broadcast(self, port: int, delay: int = 15):
        """Broadcast hostname and current time every 'delay' seconds."""
        self.log.info(f"Broadcasting on UDP port {port}...")
        self.proxy.start(MetricsProxy.INPUT_ENDPOINT, MetricsProxy.OUTPUT_ENDPOINT)
        while True:
            msg = f"HOST {platform.node()} {int(time.time())}"
            self.log.debug(f"Sending '{msg}' -> {self.BROADCAST}:{port}")

            try:
                self.sock.sendto(msg.encode(), (self.BROADCAST, port))
            except Exception:
                self.log.exception(f"Error sending to {self.BROADCAST}:{port}")

            time.sleep(delay)


class BroadcastReceiver(Disco):
    """Report UDP host discovery broadcasts."""

    def __init__(self, debug: bool = False):
        """Create UDP broadcast socket."""
        super().__init__(debug)
        self.sock = Disco.udp_socket()

    def receive(self, port: int, timeout: int = None):
        """Return hosts discovered within the timeout period."""
        self.log.info(f"Listening on UDP port {port}...")
        self.sock.bind(("", port))
        hosts = {}
        start = time.time()
        while True:
            try:
                ready = select.select([self.sock], [], [], 1)

                if ready[0]:
                    msg, addr = self.sock.recvfrom(1024)
                    hosts[addr[0]] = msg.decode()
                    self.log.info(f"Received {addr[0]} : {msg.decode()}")
                else:
                    self.log.debug("No hosts")
            except Exception:
                self.log.exception(f"Error receiving on port {port}")

            if timeout and time.time() - start >= timeout:
                return hosts


class MetricsProxy(Disco):
    """Collect metrics published on an input socket to an output socket."""

    INPUT_ENDPOINT = Disco.IPC_PATH
    OUTPUT_ENDPOINT = f"tcp://*:{Disco.PORT}"

    def __init__(self):
        """Create a zmq xpub/xsub proxy"""
        super().__init__()
        self.proxy = ThreadProxy(zmq.XSUB, zmq.XPUB)

    def start(self, input_endpoint: str, output_endpoint: str):
        """Bind the proxy sockets endpoints and start forwarding messages."""
        self.proxy.bind_in(input_endpoint)
        self.proxy.bind_out(output_endpoint)
        self.proxy.start()
        return self

    def join(self):
        """Join the background proxy thread."""
        self.proxy.join()


class MetricsPublisher(Disco):
    """Publish metrics to a configured location."""

    def __init__(self, endpoint: str = Disco.IPC_PATH):
        """Create and connect a publish socket."""
        super().__init__()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.connect(endpoint)
        time.sleep(0.05)  # zmq slow join workaround

    def publish(self, name: str, value: str = None):
        """Publish a named metric value or, if not present, current epoch time."""
        if value:
            self.socket.send_string(f"metric {name} {value}")
        else:
            self.socket.send_string(f"metric {name} {int(time.time())}")


class MetricsReceiver(Disco):
    def __init__(self):
        super().__init__()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")

    def receive(self, endpoint: str):
        self.socket.connect(endpoint)
        while True:
            msg = self.socket.recv()
            print(msg)


def configure():
    parser = argparse.ArgumentParser(description="disco.py - Host discovery and metrics toolkit")

    subparsers = parser.add_subparsers(dest="command", required=True)
    parser.add_argument("--debug", default=False, action="store_true",
                        help="Enable debug output")

    broadcast = subparsers.add_parser("broadcast", help="UDP broadcast mode")
    broadcast_mode = broadcast.add_mutually_exclusive_group(required=True)
    broadcast_mode.add_argument("--send", default=False, action="store_true",
                                help="Send UDP broadcasts")
    broadcast_mode.add_argument("--receive", default=False, action="store_true",
                                help="Receive UDP broadcasts")
    broadcast.add_argument("--port", default=Disco.PORT, type=int,
                           help=f"Target port (default: {Disco.PORT})")
    broadcast.add_argument("--delay", default=Disco.DELAY, type=int,
                           help=f"Broadcast delay (default: {Disco.DELAY})")

    metrics = subparsers.add_parser("metrics", help="Metrics mode")
    metrics_mode = metrics.add_mutually_exclusive_group(required=True)
    metrics_mode.add_argument("--publish", type=str, nargs=2, metavar=('NAME', 'VALUE'),
                              help="Publish named metric value (e.g., 'temp 73')")
    metrics_mode.add_argument("--receive", type=str, metavar='ENDPOINT',
                              help="Host endpoint (e.g., 'tcp://host:port')")
    metrics_mode.add_argument("--proxy", type=str, nargs=2, metavar=('INPUT', 'OUTPUT'),
                              help="Metrics proxy endpoints (e.g., 'ipc:///var/tmp/disco tcp://*:9000')")

    return parser.parse_args()


def main():
    args = configure()

    if args.command == "broadcast":
        if args.send:
            BroadcastServer(args.debug).broadcast(args.port, args.delay)
        elif args.receive:
            BroadcastReceiver(args.debug).receive(args.port)
    elif args.command == "metrics":
        if args.publish:
            MetricsPublisher().publish(*args.publish)
        elif args.receive:
            MetricsReceiver().receive(args.receive)
        elif args.proxy:
            MetricsProxy().start(*args.proxy).join()
    else:
        raise ValueError("Invalid command")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
