#!/bin/bash
git submodule init
git submodule update
pip3 install --user opuslib google protobuf-py3 pyaudio
