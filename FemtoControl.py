 #!/usr/bin/python3 -u
# coding: utf8
from tango import AttrWriteType, DevState
from tango.server import Device, attribute, command, device_property
import re

import socket
import time
from enum import IntEnum


class CouplingMode(IntEnum):
    AC = 0
    DC = 1


class SpeedMode(IntEnum):
    High = 0
    Low = 1


class FemtoControl(Device):
    '''FemtoControl

    Device server that communicates with an arduino with ethernet shield
    via UDP. The digital pins of the arduino control a Femto DLPCA-200 current
    amplifier.
    '''
    IPaddress = device_property(dtype=str)
    Port = device_property(dtype=int, default_value=8888)

    gain = attribute(
        label='gain',
        dtype=int,
        access=AttrWriteType.READ_WRITE,
    )

    coupling = attribute(
        label='coupling',
        dtype=CouplingMode,
        access=AttrWriteType.READ_WRITE,
    )

    speed = attribute(
        label='speed',
        dtype=SpeedMode,
        access=AttrWriteType.READ_WRITE,
    )

    temperature = attribute(
        label='temperature',
        dtype=float,
        access=AttrWriteType.READ,
        unit='degC',
    )

    amplification = attribute(
        label='amplification',
        dtype=float,
        access=AttrWriteType.READ,
        unit='V/A'
    )

    humidity = attribute(
        label='humidity',
        dtype=float,
        access=AttrWriteType.READ,
        unit='%',
    )

    overload = attribute(
        label='overload',
        dtype=bool,
        access=AttrWriteType.READ,
    )

    def init_device(self):
        super().init_device()
        self.__last_temp_read = 0
        self.__last_status_read = 0
        try:
            self.info_stream(
                f'Trying to connect to {self.IPaddress}:{self.Port}'
            )
            self.con = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self.con.connect((self.IPaddress, self.Port))
            self.con.settimeout(5)
            self.con.setblocking(True)
            idn = self.write_read('ID?')
            self.info_stream('Connection established for {:s}'.format(idn))
            self.re_temp = re.compile(r'T=([\d\.]+);H=([\d\.]+)')
        except Exception as ex:
            self.error_stream(f'Error on initialization:\n{ex}')

        self.set_state(DevState.ON)

    def delete_device(self):
        self.set_state(DevState.OFF)
        self.info_stream('A device was deleted!')

    def update_status(self):
        # avoid polling rapidly for each attribute - they are read in one go
        if time.time() - self.__last_status_read > 0.5:
            status = self.write_read("STATUS?")
            self.__gain = int(status[:3][::-1], base=2)
            coupling, speed, overload = [int(s) for s in status[3:6]]
            self.__overload = overload
            self.__speed = speed
            self.__coupling = coupling
            self.debug_stream(f'STATUS={status}')
            self.__last_status_read = time.time()

            if self.__overload:
                self.set_state(DevState.FAULT)
            else:
                self.set_state(DevState.ON)
        else:
            self.debug_stream('Skipping status read (too recent)')

    def always_executed_hook(self):
        # self.debug_stream('In always_executed_hook')
        pass

    def read_temp_humidity(self):
        '''Reading the temperature is a little slow - don't do it too often'''
        if time.time() - self.__last_temp_read > 10:
            ans = self.write_read('TEMP?')
            t_h = [float(v) for v in self.re_temp.match(ans).groups()]
            self.__temperature = t_h[0]
            self.__humidity = t_h[1]
            self.__last_temp_read = time.time()
        else:
            self.debug_stream('Skipping temp read (too recent)')

    def read_gain(self):
        self.update_status()
        return self.__gain

    def write_gain(self, value):
        self.write_read(f'GAIN={value:d}')
        # self.__gain = value

    def read_coupling(self):
        self.update_status()
        return self.__coupling

    def write_coupling(self, value):
        self.write_read(f'ACDC={value:d}')
        # self.__coupling = value

    def read_speed(self):
        self.update_status()
        return self.__speed

    def write_speed(self, value):
        self.write_read(f'SPEED={value:d}')
        # self.__speed = value

    def read_amplification(self):
        base = 5 if self.__speed else 3
        return 10**(base + self.__gain)

    def read_overload(self):
        self.update_status()
        return self.__overload

    def read_temperature(self):
        self.read_temp_humidity()
        return self.__temperature

    def read_humidity(self):
        self.read_temp_humidity()
        return self.__humidity

    @command(dtype_in=str, doc_in='command', dtype_out=str, doc_out='response')
    def write_read(self, cmd):
        try:
            self.con.send('{:s}\n'.format(cmd).encode('ascii'))
            ret = self.con.recv(1024).decode('ascii')
            while (ret.find('\n') == -1):
                ret += self.con.recv(1024).decode('ascii')
        except socket.timeout:
            self.warning_stream('Socket timeout')
            ret = ''
        except socket.error:
            self.error_stream('Socket error')
            ret = ''
        # evaluate the response

        if 'DONE' in ret:
            # write command acknowledged - nothing to return
            self.debug_stream('write command acknowledged')
            ret = ''
        else:
            ret = ret
        return ret


# start the server
if __name__ == "__main__":
    FemtoControl.run_server()
