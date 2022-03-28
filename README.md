# disco.py

A host discovery tool utilizing UDP broadcasts. This script can be useful for discovering Raspberry Pi IP addresses when it may not be prudent to maintain static assignments for a large number of devices. There are also [alternative approaches](https://github.com/Matthias-Wandel/pi_blink_ip) to solving this problem.

## Usage

```
➤ ./disco.py --help
usage: disco.py [-h] (--listen | --broadcast) [--host HOST] [--port PORT]
                [--delay DELAY] [--debug]

disco.py - Host discovery tool

optional arguments:
  -h, --help       show this help message and exit
  --listen, -l     Listen mode
  --broadcast, -b  Broadcast mode
  --host HOST      Target host (default: UDP broadcast)
  --port PORT      Target port (default: 9000)
  --delay DELAY    Broadcast delay in seconds (default: 15)
  --debug          Enable debug output
```

## Examples

```
➤ disco.py --broadcast
Sending to <broadcast>:9000...
```

```
➤ disco.py --listen
Listening on port 9000...
Received 192.168.1.125 : HOST shed 1648439527
Received 192.168.1.127 : HOST garage 1648439529
Received 192.168.1.115 : HOST cam1 1648439530
Received 192.168.1.117 : HOST cam2 1648439531
```
