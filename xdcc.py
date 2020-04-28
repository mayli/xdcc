import irc.client
import struct
import sys
from time import time
import shlex
import os
import argparse
import itertools
import random
import signal
import logging

log = logging.getLogger("verbose")
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
log.addHandler(handler)
ERASE_LINE = '\x1b[2K'

def hour_min_second(seconds):
    minutes, seconds = divmod(seconds,60)
    hours, minutes = divmod(minutes, 60)
    return "%02d:%02d:%02d" % (hours, minutes, seconds)

class DCCcat(irc.client.SimpleIRCClient):
    def __init__(self, args):
        irc.client.SimpleIRCClient.__init__(self)
        self.args = args
        self.received_bytes = 0

        self.total_size = 0
        self.last_received_bytes = 0
        self.last_print_time = 0


    def on_ctcp(self, connection, event):
        log.debug("CTCP: %s" % event.arguments)
        if event.arguments[0] != "DCC":
            return

        payload = event.arguments[1]
        parts = shlex.split(payload)
        command, filename, peer_address, peer_port, size = parts
        if command != "SEND":
            return

        self.filename = os.path.basename(filename)
        self.file = sys.stdout if self.args.stdout else  open(self.filename, "wb")

        self.total_size = int(size)
        peer_address = irc.client.ip_numstr_to_quad(peer_address)
        peer_port = int(peer_port)
        self.dcc = self.dcc_connect(peer_address, peer_port, "raw")

    def show_download_status(self):
        now = time()
        if now - self.last_print_time >= 1:
            percentage = 100*self.received_bytes/self.total_size
            speed = (self.received_bytes - self.last_received_bytes)
            erase_line_msg = '\r' + ERASE_LINE
            duration = hour_min_second((self.total_size - self.received_bytes)/speed)
            print(erase_line_msg + "%s: (%.2f%%) [%.2f MB/s] {%s}" % (self.filename,percentage,speed/(1e6),duration), end='')
            sys.stdout.flush()

            self.last_print_time = now
            self.last_received_bytes = self.received_bytes

    def on_dccmsg(self, connection, event):
        # Apparently the bots that i have used to test are both using the TURBO DCC instead
        # of the standard DCC.
        data = event.arguments[0]
        self.file.write(data.decode('utf-8') if self.args.stdout else data)
        self.received_bytes = self.received_bytes + len(data)

        # Since we are assuming a TURBO DCC transference, let close the connection when
        # the file has been completely transmitted.
        if self.received_bytes == self.total_size:
            self.dcc.disconnect()

        if not self.args.stdout:
            self.show_download_status()

    def on_dcc_disconnect(self, connection, event):
        log.debug("DCC connection closed by remote peer!")
        if not self.args.stdout:
            self.file.close()
            print("")
        self.connection.quit()

    def request_file_to_bot(self):
        log.debug("Sending command to the bot...")
        if self.args.action == "list":
            self.connection.ctcp("xdcc",self.args.bot,"send list")
        elif self.args.action == "send":
            self.connection.ctcp("xdcc",self.args.bot,"send %d" % self.args.pack)

    def on_welcome(self, c, e):
        log.debug("Welcome page of the server was reached successfully.")
        if self.args.channel:
            self.requested = False
            self.connection.join(self.args.channel)
        else:
            self.request_file_to_bot()

    def on_join(self, c, e):
        # Some channels can trigger this function multiple times

        log.debug("Joined to channel %s." % self.args.channel)
        if not self.requested:
            self.request_file_to_bot()
            self.requested = True

    def on_kick(self, c, e):
        print("You was kicked from the channel!")

    def on_part(self, c, e):
        print("You has parted from the channel!")

    def on_nicknameinuse(self, c, e):
        print("Failed! Nickname '%s' already in use" % self.args.nickname)
        self.connection.quit()

    def on_privnotice(self, c, e):
        log.debug("PRIVNOTICE: %s" % e.arguments[0])

        source = str(e.source)
        if source.startswith(self.args.bot):
            print("-%s- %s" % (source, e.arguments[0]))

    def on_disconnect(self, connection, event):
        log.debug("Disconnected!")
        sys.exit(0)

def random_nickname():
    choices = itertools.permutations("anonymous")
    choices = list(choices)
    return "".join(random.choice(choices))

parser = argparse.ArgumentParser()
parser.add_argument("--server","-s",type=str,help="server",default="irc.rizon.net")
parser.add_argument("--channel","-c",type=str,help="channel")
parser.add_argument("--port","-p",type=int,help="port number",default=6667)
parser.add_argument("--stdout","-t",action='store_true',
                    help="when used with the 'list' action, print the file to the stdout")
parser.add_argument("--nickname",'-n',type=str,
                    help="nickname to be used. The default is a random permutation of 'anonymous'",
                    default=random_nickname())
parser.add_argument("--verbose",'-v',action='store_true',help="enable verbose mode")
parser.add_argument("bot",type=str,help="bot name")
parser.add_argument("action",choices=["list",'send'],help="action to take")
parser.add_argument("pack",nargs='?',type=int,help="pack number of file")
args = parser.parse_args()

if args.action == "list" and args.pack :
    parser.error("action 'list' don't require a pack number.")
elif args.action == "send" and args.pack == None:
    parser.error("action 'send' require a pack number.")
elif args.stdout  and args.action != "list":
    parser.error("--stdout can only be used with the 'list' action")


if args.verbose:
    log.setLevel(logging.DEBUG)

log.debug("Using nickname %s" % args.nickname)

c = DCCcat(args)
def cute_exit(sig, frame):
    print("SIGINT received! Quitting...")
    c.connection.quit()

signal.signal(signal.SIGINT,cute_exit)

try:
    c.connect(args.server, args.port, args.nickname)
except irc.client.ServerConnectionError as x:
    print(x)
    print("Something bad has happened")
    sys.exit(1)

c.start()
