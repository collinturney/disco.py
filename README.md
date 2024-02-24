# 🔮 disco.py

A brokerless event and metrics toolkit for Linux based IoT devices.


## Broadcast Mode

### Examples

Periodically send UDP broadcasts that include host information.

```
➤ ./disco.py broadcast --send
Broadcasting on UDP port 9000
```

Report UDP broadcasts.

```
➤ ./disco.py broadcast --receive
Listening for broadcasts on UDP port 9000
Received broadcast from 192.168.1.125 : HOST shed 1648439527
Received broadcast from 192.168.1.127 : HOST garage 1648439529
Received broadcast from 192.168.1.115 : HOST cam1 1648439530
Received broadcast from 192.168.1.117 : HOST cam2 1648439531
```

### Usage

```
disco.py broadcast [-h] (--send | --receive)
                        [--port PORT]
                        [--delay DELAY]
                        [--debug]

optional arguments:
  -h, --help     show this help message and exit
  --send         Send UDP broadcasts
  --receive      Receive UDP broadcasts
  --port PORT    Target port (default: 9000)
  --delay DELAY  Broadcast delay (default: 15)
  --debug        Enable debug output
```

## Metrics Mode

### Examples

Publish metrics from the command line.

```
➤ ./disco.py metrics --publish temperature 73
```

Discover new hosts and report their published metrics.

```
➤ ./disco.py metrics --receive
Connecting new metrics host: 192.168.1.125
Connecting new metrics host: 192.168.1.127
Metric(host=shed values={"temperature": "73", "_time": 1683949549.3670144})
```

Forward all metrics received on a frontend endpoint to a backend endpoint.

```
➤ ./disco.py metrics --proxy
Proxying metrics ('ipc:///var/tmp/disco' -> 'tcp://*:9000')
```

### Usage

```
disco.py metrics [-h] (--publish NAME VALUE | --receive | --proxy)
                      [--frontend FRONTEND]
                      [--backend BACKEND]
                      [--debug]

optional arguments:
  -h, --help            show this help message and exit
  --publish NAME VALUE  Publish named metric value (e.g., 'temp 73')
  --receive             Report metrics from all discovered hosts
  --proxy               Metrics proxy mode
  --frontend FRONTEND   Proxy frontend (e.g., ipc:///var/tmp/disco)
  --backend BACKEND     Proxy backend (e.g., tcp://*:9000)
  --debug               Enable debug output
```

## Installation

Run the install script to register and enable the disco systemd service. The 
service will begin sending host discovery broadcasts and proxying host metrics.

```
➤ ./install.sh disco.service
```
