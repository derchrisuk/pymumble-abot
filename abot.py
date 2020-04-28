#!/usr/bin/env python
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
#from pprint import pprint
#import warnings

from thrd_party import pymumble
import pyaudio

__version__ = "0.0.9"
PCS = pymumble.callbacks.PYMUMBLE_CLBK_SOUNDRECEIVED
CHUNK = 128

pa = pyaudio.PyAudio()

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
        repr_str = ""
        for status in self:
            repr_str += "[%s] alive: %s\n" % (status.name, status.alive)
        return repr_str



class Runner(collections.UserDict):
    """ TODO """
    def __init__(self, run_dict, args_dict=None):
        self.is_ready = False
        super().__init__(run_dict)
        self.change_args(args_dict)
        self.run()

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
            print("[run] generating process for:", name)
            self[name]["process"] = Thread(name=name,
                                           target=cdict["func"],
                                           args=cdict["args"],
                                           kwargs=cdict["kwargs"])
            print("[run] starting process for:", name)
            self[name]["process"].start()
            print("[run] ", name, "started")
        print("[run] all done")
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
    def __init__(self, mumble_object, args_dict):
        print(args_dict)
        self.mumble = mumble_object
        self.stream = pa.open(input=True,
                           channels=1,
                           format=pyaudio.paInt16,
                           rate=pymumble.constants.PYMUMBLE_SAMPLERATE,
                           input_device_index=args_dict['input_device_index'],
                           frames_per_buffer=CHUNK)
        self.streamOut = pa.open(output=True,
                           channels=1,
                           format=pyaudio.paInt16,
                           rate=pymumble.constants.PYMUMBLE_SAMPLERATE,
                           output_device_index=args_dict['output_device_index'],
                           frames_per_buffer=CHUNK)
        self.streamOut.start_stream()
        self.mumble.set_receive_sound(1)
        self.mumble.callbacks.set_callback(PCS, self.sound_received_handler)
        super().__init__(self._config(), args_dict)

    def _config(self):
        raise NotImplementedError("please inherit and implement")


class Audio(MumbleRunner):
    def _config(self):
        return {"input": {"func": self.__input_loop, "process": None},
                "output": {"func": self.__output_loop, "process": None}}

    def calculate_volume(self, thread_name):
        """ TODO """
        try:
            dbel = self[thread_name]["db"]
            self["vol_vector"] = 10 ** (dbel/20)
        except KeyError:
            self["vol_vector"] = 1

    def sound_received_handler(self, user, soundchunk):
        """ play sound received from mumble server upon its arrival """
        self.streamOut.write(soundchunk.pcm)

    def __output_loop(self, periodsize):
        """ TODO """
        print("period: %i", periodsize)
        del periodsize
        return None

    def __input_loop(self, periodsize):
        """ TODO """
        self.stream.start_stream()
        while True:
            data = self.stream.read(periodsize)
            self.mumble.sound_output.add_sound(data)
        self.stream.stop_stream()
        self.stream.close()
        return True

    def input_vol(self, dbint):
        pass

class AudioPipe(MumbleRunner):
    def _config(self):
        return {"PipeInput": {"func": self.__input_loop, "process": None},
                "PipeOutput": {"func": self.__output_loop, "process": None}}

    def __output_loop(self, periodsize):
        return None

    def __input_loop(self, periodsize, path):
        while True:
            with open(path) as fifo_fd:
                while True:
                    data = fifo_fd.read(periodsize)
                    self.mumble.sound_output.add_sound(data)


class Parser(MumbleRunner):
    pass

def prepare_mumble(host, user, password="", certfile=None,
                   codec_profile="audio", bandwidth=96000, channel=None):
    """Will configure the pymumble object and return it"""

    abot = pymumble.Mumble(host, user, certfile=certfile, password=password)

    abot.set_application_string("abot (%s)" % __version__)
    abot.set_codec_profile(codec_profile)
    abot.start()
    abot.is_ready()
    abot.set_bandwidth(bandwidth)
    if channel:
        try:
            abot.channels.find_by_name(channel).move_in()
        except pymumble.channels.UnknownChannelError:
            print("Tried to connect to channel:", "'" + channel + "'. ", "Got this Error:")
            print("Available Channels:")
            print(abot.channels)
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

    parser.add_argument("-s", "--setperiodsize", dest="periodsize", type=int, default=256,
                        help="Lower values mean less delay. WARNING:Lower values could be unstable")

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

    input_device_index = None
    output_device_index = None

    if args.list_devices:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            input_chn = dev.get('maxInputChannels', 0)
            output_chn = dev.get('maxInputChannels', 0)
            if True or input_chn > 0 or output_chn > 0:
                name = dev.get('name')
                rate = dev.get('defaultSampleRate')
                print("Index {i}: {name} (Max inputs {input_chn}, Max output {output_chn}, Default @ {rate} Hz)".format(
                    i=i, name=name, input_chn=input_chn, output_chn=output_chn, rate=int(rate)

                ))
        default_in = pa.get_default_input_device_info()
        default_out = pa.get_default_output_device_info()
        print("Default input: {name}".format(name=default_in.get('name')))
        print("Default output: {name}".format(name=default_out.get('name')))
        sys.exit()

    if args.input:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get('name') == args.input:
                input_device_index = i
                break
        if input_device_index is None:
            print("Device not found: {name}".format(name = args.input))
            sys.exit()

    if args.output:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get('name') == args.output:
                output_device_index = i
                break
        if output_device_index is None:
            print("Device not found: {name}".format(name = args.ouput))
            sys.exit()

    abot = prepare_mumble(args.host, args.user, args.password, args.certfile,
                          "audio", args.bandwidth, args.channel)

    if args.fifo_path:
        client = AudioPipe(abot, {"output": {"args": (args.periodsize, ),
                                            "kwargs": None},
                                 "input": {"args": (args.periodsize, args.fifo_path),
                                           "kwargs": None}
                                }
                         )
    else:
        client = Audio(abot, {"output": {"args": (args.periodsize, ),
                                        "kwargs": None},
                             "input": {"args": (args.periodsize, ),
                                       "kwargs": None},
                              "input_device_index": input_device_index,
                              "output_device_index": output_device_index
                            }
                     )
    if preserve_thread:
        while True:
            print(client.status())
            sleep(60)

if __name__ == "__main__":
    sys.exit(main())


