#!/usr/bin/python3
"""
TITLE:  abot
AUTHOR: Ranomier (ranomier@fragomat.net)
DESC:   a simple bot that receives sound from a sound device (for me jack audio kit)
"""

import argparse
import sys
from threading import Thread
from time import sleep
import collections
import queue
import array
import webrtcvad
import logging
#from pprint import pprint
#import warnings

from thrd_party import pymumble
import pyaudio

__version__ = "0.0.1"

LOG_LEVEL = logging.DEBUG

logger = logging.getLogger("abot")
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stderr)
handler.setLevel(LOG_LEVEL)
#formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
#handler.setFormatter(formatter)
logger.addHandler(handler)

pa = pyaudio.PyAudio( )

class Status(collections.UserList):
    def __init__(self, runner_obj):
        self.__runner_obj = runner_obj
        self.scheme = collections.namedtuple("thread_info", ("name", "alive"))
        super().__init__(self.__gather_status())

    def __gather_status(self):
        result = []
        for meta in self.__runner_obj.values():
            result.append(self.scheme(meta["process"].name,
                                      meta["process"].is_alive()))
        return result

    def __repr__(self):
        repr_str = "\n"
        for status in self:
            repr_str += "[%s] alive: %s\n" % (status.name, status.alive)
        return repr_str

class Runner(collections.UserDict):
    """ TODO """
    def __init__(self, run_dict, args_dict=None):
        self.is_ready = False
        super().__init__(run_dict)
        self.change_args(args_dict)

    def change_args(self, args_dict):
        """ TODO """
        for name in self.keys():
            if name in args_dict:
                self[name]["args"] = args_dict[name]["args"]
                self[name]["kwargs"] = args_dict[name]["kwargs"]
            else:
                self[name]["args"] = None
                self[name]["kwargs"] = None


    def run(self):
        """ TODO """
        for name, cdict in self.items():
            logger.debug("[run] generating process for: " + name)
            self[name]["process"] = Thread(name=name,
                                           target=cdict["func"],
                                           args=cdict["args"],
                                           kwargs=cdict["kwargs"])
            logger.debug("[run] starting process for: " + name)
            self[name]["process"].start()
            logger.info("[run] " + name + " started")
        logger.debug("[run] all done")
        self.is_ready = True

    def status(self):
        """ TODO """
        if self.is_ready:
            return Status(self)
        else:
            return list()

    def stop(self, name=""):
        raise NotImplementedError("Sorry")


class MumbleRunner(Runner):
    def __init__(self, mumble_object, args):
        logger.debug(args)
        self.mumble = mumble_object
        self.rate = pymumble.constants.PYMUMBLE_SAMPLERATE
        self.periodSize = args.periodSize
        self.chunkSize = int(self.rate * self.periodSize / 1000);
        if args.vad >= 0:
            if not self.periodSize in (10,20,30):
                if self.periodSize > 30:
                    self.vadBlock = int(self.rate * 30 / 1000)
                elif self.periodSize > 20:
                    self.vadBlock = int(self.rate * 20/ 1000)
                elif self.periodSize > 10:
                    self.vadBlock = int(self.rate * 10 / 1000)
                else:
                    self.periodSize = 10
                    self.chunkSize = int(self.rate * self.periodSize / 1000)
                    self.vadBlock = chunkSize
                logger.info("vad requested, adjusting period size to %i", self.periodSize)
                logger.info("vad requested, adjusting vad-chunk to %i", self.vadBlock)
            else:
                self.vadBlock = self.chunkSize
        if args.vad >= 0:
            self.vad = webrtcvad.Vad(args.vad)            
            self.numVadFrames = int(self.rate * args.vadLatency / self.chunkSize) # keep audio running for this many frames
            logger.info("vad-frames: %i", self.numVadFrames)
        else:
            self.vad = None
        logger.info("rate: %i", self.rate)
        logger.info("chunk size: %i", self.chunkSize)
        self.stream_in = pa.open(input=True,
                                 start=False,
                                 channels=1,
                                 format=pyaudio.paInt16,
                                 rate=self.rate,
                                 input_device_index=args.input_device_index,
                                 frames_per_buffer=self.chunkSize)
        self.stream_out = pa.open(output=True,
                                  start=False,
                                  channels=1,
                                  format=pyaudio.paInt16,
                                  rate=self.rate,
                                  output_device_index=args.output_device_index,
                                  frames_per_buffer=self.chunkSize)
        self.mumble.set_receive_sound(1)
        self.mumble.callbacks.set_callback(pymumble.callbacks.PYMUMBLE_CLBK_SOUNDRECEIVED, self.sound_received_handler)
        super().__init__(self._config(),
                         {"mumble-output": {"args": (), "kwargs": None},
                          "sound-input": {"args": (),"kwargs": None},
                          "sound-output": {"args": (),"kwargs": None} })

    def _config(self):
        raise NotImplementedError("please inherit and implement")


class Audio(MumbleRunner):
    def __init__(self, mumble_object, args):
        super().__init__(mumble_object, args)
        self.received_queue = queue.Queue()
        self.sound_input_queue = queue.Queue()
        self.run()

    def _config(self):
        return {"mumble-output": {"func": self.__mumble_output_loop, "process": None},
                "sound-input": {"func": self.__sound_input_loop, "process": None},
                "sound-output": {"func": self.__sound_output_loop, "process": None}}

    def sound_received_handler(self, user, soundchunk):
        """ play sound received from mumble server upon its arrival """
        self.received_queue.put(soundchunk)

    def __sound_output_loop(self):
        """ TODO """
        # keep the stream running with zero-data for some time
        nullBuffer = array.array('h', [0] * self.chunkSize)
        nullSeconds = 0.25
        nullChunks = int(self.rate * nullSeconds / self.chunkSize)
        nullCounter = -1
        while True:
            if nullCounter == -1:
                # blocking input until we get something
                data = self.received_queue.get().pcm
                nullCounter = nullChunks
                self.stream_out.start_stream()
            else:
                # non-blocking input until we stop the stream after some amount of silence
                try:
                    data = self.received_queue.get(False).pcm
                except queue.Empty:
                    data = nullBuffer.tobytes()
                    nullCounter -= 1
            self.stream_out.write(data)
            if nullCounter == 0:
                nullCounter = -1
                self.stream_out.stop_stream()
        self.stream_out.stop_stream()
        self.stream_out.close()
        return True

    def __sound_input_loop(self):
        """ TODO """
        self.stream_in.start_stream()
        while True:
            self.sound_input_queue.put(self.stream_in.read(self.chunkSize, exception_on_overflow = False))
        self.stream_in.stop_stream()
        self.stream_in.close()
        return True

    def __mumble_output_loop(self):
        """ TODO """
        if self.vad:
            keepRunningFrames = 0
            while True:
                data = self.sound_input_queue.get();
                #
                # VAD supports only 10/20/30 ms
                #
                if self.vad.is_speech(data[:2*self.vadBlock], self.rate):
                    self.mumble.sound_output.add_sound(data)
                    keepRunningFrames = self.numVadFrames
                elif keepRunningFrames > 0:
                    self.mumble.sound_output.add_sound(data)
                    keepRunningFrames -= 1
        else:
            while True:
                data = self.sound_input_queue.get();
                self.mumble.sound_output.add_sound(data)
        return True

class AudioPipe(MumbleRunner):
    def __init__(self, mumble_object, args):
        super().__init__(mumble_object, args)
        self.path = args.fifo_path

    def _config(self):
        return {"PipeInput": {"func": self.__input_loop, "process": None},
                "PipeOutput": {"func": self.__output_loop, "process": None}}

    def __output_loop(self):
        return None

    def __input_loop(self):
        while True:
            with open(self.path) as fifo_fd:
                while True:
                    data = fifo_fd.read(self.chunkSize)
                    if not self.vad or self.vad.is_speech(data, pymumble.constants.PYMUMBLE_SAMPLERATE):
                        self.mumble.sound_output.add_sound(data)
        return True

def handle_mumble_connect():
    logger.info("Connected to Mumble-daemon.")

def handle_mumble_disconnect():
    logger.warning("Disconnected dfrom Mumble-daemon.")

def prepare_mumble(host, user, password="", certfile=None,
                   codec_profile="audio", bandwidth=96000, channel=None):
    """Will configure the pymumble object and return it"""

    abot = pymumble.Mumble(host, user, certfile=certfile, password=password, reconnect=True)

    abot.set_application_string("abot (%s)" % __version__)
    abot.set_codec_profile(codec_profile)
    abot.callbacks.set_callback(pymumble.callbacks.PYMUMBLE_CLBK_CONNECTED, handle_mumble_connect)
    abot.callbacks.set_callback(pymumble.callbacks.PYMUMBLE_CLBK_DISCONNECTED, handle_mumble_disconnect)
    abot.start()
    abot.is_ready()
    abot.set_bandwidth(bandwidth)
    if channel:
        try:
            abot.channels.find_by_name(channel).move_in()
        except pymumble.channels.UnknownChannelError:
            logger.error("Tried to connect to channel:", "'" + channel + "'. ", "Got this Error:")
            logger.error("Available Channels:")
            logger.error(abot.channels)
            sys.exit(1)
    return abot

def main(preserve_thread=True):
    """swallows parameter. TODO: move functionality away"""
    parser = argparse.ArgumentParser(description='Alsa input to mumble')
    parser.add_argument("-H", "--host", dest="host", type=str,
                        help="A hostame of a mumble server")

    parser.add_argument("-u", "--user", dest="user", type=str,
                        help="Username you wish, Default=abot")

    parser.add_argument("-p", "--password", dest="password", type=str, default="",
                        help="Password if server requires one")

    parser.add_argument("--vad", dest="vad", type=int, default=0,
                        help="""Use webrtcvad for void recognition. The argument ranges between 0 and 3
and controls the aggressiveness of the underlying webrtcvad machine where
0 is least aggressive and 3 most""")

    parser.add_argument("--vad-latency", dest="vadLatency", type=int, default=2,
                        help="""After speech is detected auto samples continue to be
transferred for this many seconds in order to stabilize the connection""")

    parser.add_argument("-s", "--setperiod", dest="periodSize", type=int, default=20,
                        help="Length in ms of the sound packages send to the server. Lower values mean less delay. When using vad the length must be 10, 20 or 30ms.")

    parser.add_argument("-b", "--bandwidth", dest="bandwidth", type=int, default=96000,
                        help="Bandwith of the bot (in bytes/s). Default=96000")

    parser.add_argument("-c", "--certificate", dest="certfile", type=str, default=None,
                        help="Path to an optional openssl certificate file")

    parser.add_argument("-C", "--channel", dest="channel", type=str, default=None,
                        help="Channel name as string")

    parser.add_argument("-f", "--fifo", dest="fifo_path", type=str, default=None,
                        help="Read from FIFO (EXPERMENTAL)")

    parser.add_argument("--list-devices", dest="list_devices", action="store_true",
                        help="List output devices")

    parser.add_argument("--input", dest="input", type=str, default=None,
                        help="Input device")

    parser.add_argument("--output", dest="output", type=str, default=None,
                        help="Output device")

    args = parser.parse_args()

    args.input_device_index = None
    args.output_device_index = None

    if args.list_devices:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            input_chn = dev.get('maxInputChannels', 0)
            output_chn = dev.get('maxInputChannels', 0)
            if True or input_chn > 0 or output_chn > 0:
                name = dev.get('name')
                rate = dev.get('defaultSampleRate')
                message = "Index {i}: {name} (Max inputs {input_chn}, Max output {output_chn}, Default @ {rate} Hz)".format(
                    i=i, name=name, input_chn=input_chn, output_chn=output_chn, rate=int(rate))
                logger.info(message)
                print(message)
        default_in = pa.get_default_input_device_info()
        default_out = pa.get_default_output_device_info()
        message = "Default input: {name}".format(name=default_in.get('name'))
        logger.info(message)
        print(message)
        message = "Default output: {name}".format(name=default_out.get('name'))
        logger.info(message)
        sys.exit()

    if args.input:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get('name') == args.input:
                args.input_device_index = i
                break
        if args.input_device_index is None:
            logger.critical("Device not found: {name}".format(name = args.input))
            sys.exit()

    if args.output:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get('name') == args.output:
                args.output_device_index = i
                break
        if args.output_device_index is None:
            logger.critical("Device not found: {name}".format(name = args.ouput))
            sys.exit()

    abot = prepare_mumble(args.host, args.user, args.password, args.certfile,
                          "audio", args.bandwidth, args.channel)

    if args.fifo_path:
        client = AudioPipe(abot, args)
    else:
        client = Audio(abot, args)

    if preserve_thread:
        while True:
            logger.info(client.status())
            sleep(60)

if __name__ == "__main__":
    sys.exit(main())
