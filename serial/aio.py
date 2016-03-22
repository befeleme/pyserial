#!/usr/bin/env python3
#
# Experimental implementation of asyncio support.
#
# This file is part of pySerial. https://github.com/pyserial/pyserial
# (C) 2015 Chris Liechti <cliechti@gmx.net>
#
# SPDX-License-Identifier:    BSD-3-Clause
"""\
Support asyncio with serial ports. EXPERIMENTAL

Posix platforms only, Python 3.4+ only.

Windows event loops can not wait for serial ports with the current
implementation. It should be possible to get that working though.
"""
import asyncio
import serial
import logging


class SerialTransport(asyncio.Transport):
    def __init__(self, loop, protocol, serial_instance):
        self._loop = loop
        self._protocol = protocol
        self.serial = serial_instance
        self._closing = False
        self._paused = False
        # XXX how to support url handlers too
        self.serial.timeout = 0
        self.serial.nonblocking()
        loop.call_soon(protocol.connection_made, self)
        # only start reading when connection_made() has been called
        loop.call_soon(loop.add_reader, self.serial.fd, self._read_ready)

    def __repr__(self):
        return '{self.__class__.__name__}({self._loop}, {self._protocol}, {self.serial})'.format(self=self)

    def close(self, exc=None):
        if self._closing:
            return
        self._closing = True
        self._loop.remove_reader(self.serial.fd)
        self.serial.close()
        self._loop.call_soon(self._protocol.connection_lost, exc)

    def _read_ready(self):
        try:
            data = self.serial.read(1024)
        except serial.SerialException as e:
            self.close(exc=e)
        else:
            if data:
                self._protocol.data_received(data)

    def write(self, data):
        try:
            self.serial.write(data)
        except serial.SerialException as e:
            self.close(exc=e)

    def can_write_eof(self):
        return False

    def pause_reading(self):
        if self._closing:
            raise RuntimeError('Cannot pause_reading() when closing')
        if self._paused:
            raise RuntimeError('Already paused')
        self._paused = True
        self._loop.remove_reader(self._sock_fd)
        if self._loop.get_debug():
            logging.debug("%r pauses reading", self)

    def resume_reading(self):
        if not self._paused:
            raise RuntimeError('Not paused')
        self._paused = False
        if self._closing:
            return
        self._loop.add_reader(self._sock_fd, self._read_ready)
        if self._loop.get_debug():
            logging.debug("%r resumes reading", self)

    #~ def set_write_buffer_limits(self, high=None, low=None):
    #~ def get_write_buffer_size(self):
    #~ def writelines(self, list_of_data):
    #~ def write_eof(self):
    #~ def abort(self):


@asyncio.coroutine
def create_serial_connection(loop, protocol_factory, *args, **kwargs):
    ser = serial.Serial(*args, **kwargs)
    protocol = protocol_factory()
    transport = SerialTransport(loop, protocol, ser)
    return (transport, protocol)


@asyncio.coroutine
def open_serial_connection(*,
                           loop=None,
                           limit=asyncio.streams._DEFAULT_LIMIT,
                           **kwargs):
    """A wrapper for create_serial_connection() returning a (reader,
    writer) pair.

    The reader returned is a StreamReader instance; the writer is a
    StreamWriter instance.

    The arguments are all the usual arguments to Serial(). Additional
    optional keyword arguments are loop (to set the event loop instance
    to use) and limit (to set the buffer limit passed to the
    StreamReader.

    This function is a coroutine.
    """
    if loop is None:
        loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader(limit=limit, loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    transport, _ = yield from create_serial_connection(
        loop=loop,
        protocol_factory=lambda: protocol,
        **kwargs)
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return reader, writer


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# test
if __name__ == '__main__':
    class Output(asyncio.Protocol):
        def connection_made(self, transport):
            self.transport = transport
            print('port opened', transport)
            transport.serial.rts = False
            transport.write(b'hello world\n')

        def data_received(self, data):
            print('data received', repr(data))
            self.transport.close()

        def connection_lost(self, exc):
            print('port closed')
            asyncio.get_event_loop().stop()

    loop = asyncio.get_event_loop()
    coro = create_serial_connection(loop, Output, '/dev/ttyUSB0', baudrate=115200)
    loop.run_until_complete(coro)
    loop.run_forever()
    loop.close()
