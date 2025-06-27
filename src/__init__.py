# This file makes 'src' a Python package.

# Optionally, you can make frequently used classes available directly from the package level
# For example:
# from .packet_handler import Packet
# from .tcp_client import TCPClient
# from .tcp_server import TCPServer
# from .udp_client import UDPClient
# from .udp_server import UDPServer

# This allows imports like: from src import Packet

# For now, keeping it simple. Users will import like: from src.tcp_client import TCPClient
# Or, if running scripts within src that refer to siblings: from .tcp_client import TCPClient

# Define __all__ if you want to specify what `from src import *` imports
# __all__ = ['Packet', 'TCPClient', 'TCPServer', 'UDPClient', 'UDPServer']
