#!/usr/bin/env python3

import argparse
import json
import logging
import logging.handlers
import os
import platform
import select
import socket
import sys
import threading
import time
import queue
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
    def udp_socket() -> socket:
        """Returns a socket configured for UDP broadcasts."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(0)
        return sock


class Metric(object):
    """Disco metric representation."""

    TOPIC = "metric"

    def __init__(self, host: str, values: dict):
        if not all((host, values)):
            raise ValueError("Metric requires host and values")

        self.host = host
        self.values = values
        self.values.setdefault("_time", time.time())

    def __repr__(self) -> str:
        return f"Metric(host={self.host} values={json.dumps(self.values)})"

    def serialize(self) -> bytes:
        return f"{Metric.TOPIC} {self.host} {json.dumps(self.values)}".encode()

    @staticmethod
    def parse(data: bytes) -> "Metric":
        msg = data.decode().strip().removeprefix(f"{Metric.TOPIC} ")
        host, values = msg.split(" ", 1)
        return Metric(host, json.loads(values))


class BroadcastPublisher(Disco):
    """Publish UDP host discovery packets."""

    def __init__(self, **kwargs):
        """Create UDP broadcast socket and create a local metrics proxy."""
        debug = kwargs.get("debug", False)
        self.port = kwargs.get("port", Disco.PORT)

        super().__init__(debug)
        self.sock = Disco.udp_socket()
        self.proxy = MetricsProxy()

    def publish(self, delay: int = Disco.DELAY):
        """Broadcast hostname and current time every 'delay' seconds."""
        self.log.info(f"Broadcasting on UDP port {self.port}")
        self.proxy.start()
        while True:
            msg = f"HOST {platform.node()} {int(time.time())}"
            self.log.debug(f"Sending '{msg}' -> {self.BROADCAST}:{self.port}")

            try:
                self.sock.sendto(msg.encode(), (self.BROADCAST, self.port))
            except Exception:
                self.log.exception(f"Error sending to {self.BROADCAST}:{self.port}")

            time.sleep(delay)


class BroadcastReceiver(Disco):
    """Report UDP host discovery broadcasts."""

    def __init__(self, **kwargs):
        """Create UDP broadcast socket."""
        debug = kwargs.get("debug", False)
        self.port = kwargs.get("port", Disco.PORT)

        super().__init__(debug)
        self.sock = Disco.udp_socket()
        self.sock.bind(("", self.port))

    def receive(self, timeout: int = None) -> dict:
        """Return hosts discovered within the timeout period."""
        self.log.debug(f"Listening for broadcasts on UDP port {self.port}")
        hosts = {}
        start = time.time()
        while True:
            try:
                ready = select.select([self.sock], [], [], 1)

                if ready[0]:
                    msg, addr = self.sock.recvfrom(1024)
                    hosts[addr[0]] = msg.decode()
                    self.log.debug(f"Received broadcast from {addr[0]} : {msg.decode()}")
            except Exception:
                self.log.exception(f"Error receiving on port {port}")

            if timeout and time.time() - start >= timeout:
                return hosts


class MetricsProxy(Disco):
    """Collect metrics published on an input socket to an output socket."""

    def __init__(self, **kwargs):
        """Create a zmq xpub/xsub proxy and bind its sockets."""
        debug = kwargs.get("debug", False)
        self.frontend = kwargs.get("frontend", Disco.IPC_PATH)
        self.backend = kwargs.get("backend", f"tcp://*:{Disco.PORT}")

        super().__init__(debug)
        self.proxy = ThreadProxy(zmq.XSUB, zmq.XPUB)
        self.proxy.bind_in(self.frontend)
        self.proxy.bind_out(self.backend)

    def start(self) -> "MetricsProxy":
        """Begin forwarding messages."""
        self.log.info(f"Proxying metrics ('{self.frontend}' -> '{self.backend}')")
        self.proxy.start()
        return self

    def join(self):
        """Join the background proxy thread."""
        self.proxy.join()


class MetricsPublisher(Disco):
    """Publish metric values to a configured endpoint."""

    def __init__(self, **kwargs):
        """Create and connect a publishing socket."""
        debug = kwargs.get("debug", False)
        endpoint = kwargs.get("endpoint", Disco.IPC_PATH)
        self.host = kwargs.get("host", platform.node())

        super().__init__(debug)
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.connect(endpoint)
        time.sleep(0.05)  # zmq slow join workaround

    def publish(self, values: dict):
        """Publish metric values."""
        metric = Metric(self.host, values)
        self.socket.send(metric.serialize())


class MetricsReceiver(Disco):
    """Discover new hosts and consolidate their published metrics."""

    def __init__(self, **kwargs):
        """Initialize host tracking, sockets, and BroadcastReceiver."""
        self.debug = kwargs.get("debug", False)
        super().__init__(self.debug)

        self.context = zmq.Context()

        # delay (in seconds) between sub socket resets
        self.reset_delay = kwargs.get("reset_delay", 3600)
        # last reset time
        self.reset_time = time.time()

        self.new_hosts = set()
        self.connected_hosts = set()
        self.running = True
        self.lock = threading.Lock()
        self.metrics_queue = queue.Queue(maxsize=10_000)

        self._initialize_sub_socket()
        self._start_host_discovery()
        self._start_metrics_receiver()

    def get_metric(self):
        """Return the next metric from the FIFO queue."""
        try:
            return self.metrics_queue.get(block=True, timeout=1)
        except queue.Empty:
            return None

    def shutdown(self):
        """Shutdown and join background threads."""
        self.running = False
        self.discovery.join()
        self.receiver.join()

    def _initialize_sub_socket(self):
        """Create and configure sub socket."""
        self.metric_subs = self.context.socket(zmq.SUB)
        self.metric_subs.setsockopt(zmq.SUBSCRIBE, Metric.TOPIC.encode())

    def _start_host_discovery(self):
        """Start host discovery thread."""
        self.broadcast = BroadcastReceiver(debug=self.debug, port=Disco.PORT)
        self.discovery = threading.Thread(target=self._receive_broadcasts)
        self.discovery.start()

    def _start_metrics_receiver(self):
        """Start metrics receiver thread."""
        self.receiver = threading.Thread(target=self._receive_metrics)
        self.receiver.start()

    def _receive_broadcasts(self):
        """Listen for host broadcasts."""
        while self.running:
            hosts = self.broadcast.receive(10)
            self.lock.acquire()
            self.new_hosts = hosts
            self.lock.release()

    def _receive_metrics(self):
        """Receive metrics and update metrics host connections."""
        poller = zmq.Poller()
        poller.register(self.metric_subs)

        while self.running:
            sockets = dict(poller.poll(1000))

            if self.metric_subs in sockets and sockets[self.metric_subs] == zmq.POLLIN:
                msg = self.metric_subs.recv()
                self._process(msg)

            if self.reset_delay and time.time() - self.reset_time >= self.reset_delay:
                self.reset_time = time.time()
                # unregister sub socket with the active poller
                poller.unregister(self.metric_subs)
                # reset sub socket and connected host state
                self._reset_connections()
                # re-register new sub socket with the active poller
                poller.register(self.metric_subs)
            else:
                self._connect_new_hosts()

    def _process(self, msg: str):
        """Parse and enqueue an incoming metric message."""
        try:
            metric = Metric.parse(msg)
            self.metrics_queue.put(metric, block=True, timeout=None)
        except Exception:
            self.log.exception(f"Error processing metrics message: {msg}")

    def _connect_new_hosts(self):
        """Ensure all new hosts are connected for metrics."""
        self.lock.acquire()
        for host in self.new_hosts:
            if host not in self.connected_hosts:
                self.log.info(f"Connecting new metrics host: {host}")
                self.metric_subs.connect(f"tcp://{host}:{Disco.PORT}")
                self.connected_hosts.add(host)
        self.new_hosts.clear()
        self.lock.release()

    def _reset_connections(self):
        """Reset all metrics host connections."""
        self.log.info("Resetting all metrics host connections")
        self.lock.acquire()
        self.metric_subs.close()
        self._initialize_sub_socket()
        self.connected_hosts.clear()
        self.lock.release()


def configure():
    parser = argparse.ArgumentParser(description="disco.py - Host discovery and metrics toolkit")

    subparsers = parser.add_subparsers(dest="command", required=True)

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
    broadcast.add_argument("--debug", default=False, action="store_true",
                           help="Enable debug output")

    metrics = subparsers.add_parser("metrics", help="Metrics mode")
    metrics_mode = metrics.add_mutually_exclusive_group(required=True)
    metrics_mode.add_argument("--publish", type=str, nargs=2, metavar=('NAME', 'VALUE'),
                              help="Publish named metric value (e.g., 'temp 73')")
    metrics_mode.add_argument("--receive", default=False, action="store_true",
                              help="Report metrics from all discovered hosts")
    metrics_mode.add_argument("--proxy", default=False, action="store_true",
                              help="Metrics proxy mode")

    metrics.add_argument("--frontend", type=str, default=f"{Disco.IPC_PATH}",
                         help=f"Proxy frontend (e.g., {Disco.IPC_PATH})")
    metrics.add_argument("--backend", type=str, default=f"tcp://*:{Disco.PORT}",
                         help=f"Proxy backend (e.g., tcp://*:{Disco.PORT})")
    metrics.add_argument("--debug", default=False, action="store_true",
                         help="Enable debug output")

    return parser.parse_args()


def main():
    args = configure()

    if args.command == "broadcast":
        if args.send:
            BroadcastPublisher(debug=True, port=args.port).publish(args.delay)
        elif args.receive:
            BroadcastReceiver(debug=True, port=args.port).receive()
    elif args.command == "metrics":
        if args.publish:
            name, value = args.publish
            MetricsPublisher(debug=args.debug).publish({name: value})
        elif args.receive:
            receiver = MetricsReceiver(debug=args.debug)
            while True:
                metric = receiver.get_metric()

                if metric:
                    print(metric)
        elif args.proxy:
            proxy = MetricsProxy(frontend=args.frontend, backend=args.backend)
            proxy.start()
            proxy.join()
    else:
        raise ValueError("Invalid command")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
