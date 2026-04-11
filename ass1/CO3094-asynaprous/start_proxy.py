# reverse_proxy.py
#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course,
# and is released under the "MIT License Agreement". Please see the LICENSE
# file that should have been included as part of this package.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#


"""
start_proxy
~~~~~~~~~~~~~~~~~

Entry point for launching the proxy server.  Parses command-line arguments,
reads virtual-host definitions from ``config/proxy.conf``, and hands the
resulting routing table to ``daemon.create_proxy``.

Config format (subset of NGINX-style)::

    host "192.168.56.114:8080" {
        proxy_pass http://192.168.56.114:9000;
    }

    host "app2.local" {
        proxy_pass http://192.168.56.114:9002;
        proxy_pass http://192.168.56.114:9003;
        dist_policy round-robin
    }

Returned routes dict::

    {
        "192.168.56.114:8080": ("192.168.56.114:9000", "round-robin"),
        "app2.local":          (["192.168.56.114:9002",
                                 "192.168.56.114:9003"], "round-robin"),
    }

Requirements:
--------------
- socket, threading, argparse, re: standard library.
- daemon.create_proxy: initialises and starts the proxy server.
"""

import socket
import threading
import argparse
import re
from urllib.parse import urlparse
from collections import defaultdict

from daemon import create_proxy

PROXY_PORT = 8080


def parse_virtual_hosts(config_file):
    """
    Parses virtual-host blocks from an NGINX-style config file and returns a
    routing table understood by :func:`daemon.proxy.resolve_routing_policy`.

    Each ``host`` block may contain:

    * One or more ``proxy_pass http://HOST:PORT;`` directives.
    * An optional ``dist_policy STRATEGY`` directive (default: ``round-robin``).

    **Return format**

    .. code-block:: python

        {
            hostname: (backend_or_list, policy),
            ...
        }

    Where ``backend_or_list`` is:

    * A plain ``str`` (``"HOST:PORT"``) when there is exactly one
      ``proxy_pass`` entry.
    * A ``list[str]`` when there are multiple ``proxy_pass`` entries.

    :param config_file (str): Path to the proxy configuration file.
    :rtype dict: Routing table ``{hostname: (backend_or_list, policy)}``.
    """

    with open(config_file, 'r') as f:
        config_text = f.read()

    # Match every  host "NAME" { ... }  block (DOTALL so '.' crosses newlines)
    host_blocks = re.findall(
        r'host\s+"([^"]+)"\s*\{(.*?)\}',
        config_text,
        re.DOTALL
    )

    routes = {}

    for host, block in host_blocks:
        # ------------------------------------------------------------------ proxy_pass entries
        # Captures the HOST:PORT part of  proxy_pass http://HOST:PORT;
        proxy_passes = re.findall(
            r'proxy_pass\s+http://([^\s;/]+)',
            block
        )

        # ------------------------------------------------------------------ dist_policy
        policy_match = re.search(r'dist_policy\s+(\S+)', block)
        policy = policy_match.group(1) if policy_match else 'round-robin'

        # ------------------------------------------------------------------ build entry
        if len(proxy_passes) == 0:
            print("[Config] WARNING – host '{}' has no proxy_pass, skipping".format(host))
            continue
        elif len(proxy_passes) == 1:
            backend_or_list = proxy_passes[0]          # single str
        else:
            backend_or_list = proxy_passes             # list of strs

        routes[host] = (backend_or_list, policy)

    # Debug print
    print("[Config] Parsed routes:")
    for key, value in routes.items():
        print("   '{}' → {}".format(key, value))

    return routes


if __name__ == "__main__":
    """
    Entry point for launching the proxy server.

    CLI arguments:

    :arg --server-ip (str):  IP address to bind (default: 0.0.0.0).
    :arg --server-port (int): Port to bind (default: 8080).
    """

    parser = argparse.ArgumentParser(
        prog='Proxy',
        description='Start the proxy process',
        epilog='Proxy daemon'
    )
    parser.add_argument('--server-ip', default='0.0.0.0',
                        help='IP address to bind the proxy. Default is 0.0.0.0')
    parser.add_argument('--server-port', type=int, default=PROXY_PORT,
                        help='Port number to bind the proxy. Default is {}.'.format(PROXY_PORT))

    args = parser.parse_args()
    ip = args.server_ip
    port = args.server_port

    routes = parse_virtual_hosts("config/proxy.conf")
    create_proxy(ip, port, routes)
