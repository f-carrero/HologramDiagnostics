#!/usr/bin/env python3
#
# This code provide a robust serial interface to a modem. 
# Cory Dixon, Hologram
#

#from tkinter import W
import serial
import time
import sys
import glob
import os
import re


# helper function to perform sort
def atoi(text):
    return int(text) if text.isdigit() else text

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]


""" Lists serial port names

	:raises EnvironmentError:
		On unsupported or unknown platforms
	:returns:
		A list of the serial ports available on the system
"""
def serial_ports():
	# Windows OS
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    # Linux OS
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    # Mac OS
    elif sys.platform.startswith('darwin'): 
        ports = glob.glob('/dev/tty.*')
    # Some other OS
    else:
        raise EnvironmentError('Unsupported platform')

	# Mainly for MacOS
    user = os.environ.get('USER').lower()
    if user:
        user = user.lower()

    # Store port names
    result = []
    for port in ports:
        if user in port.lower(): continue
        elif 'bluetooth' in port.lower(): continue

        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass

    result.sort(key=natural_keys)
    return result

""" Modem AT Command Manager Class """
class ATManager:
	def __init__(self, serial_timeout=5, msg_timeout=1, print_debug = False):
		self.print_debug = print_debug
		self.ser = None
		self.init_time = time.time()
		self.sent_cmd = None
		self.last_rx = time.time()
		self.serial_timeout = serial_timeout
		self.msg_timeout = msg_timeout
		self.msg_timeout_def = msg_timeout
		self.send_at = None
		self.last_sms = [] # message from last urc code
		self.have_sms = False
		self.ping_count = 0
		self.have_ping = False
		self.last_ping = 0
	
	# The default message timeout is 1 second. However, some commands like the AT+COPS=?
	# can take much longer. You should cal set_msg_timeout(big_number) for those commands
	# and then it is advised to set the timeout back to 1 set_msg_timeout(1)
	def set_msg_timeout(self, val):
		if val is not None:
			self.msg_timeout = val
			self.msg_timeout_def = val

	# Assign an AT command to the command manager
	def set_cmd(self, val):
		self.send_at = val
		#print("setting cmd {}".format(self.send_at))

	# Open serial port
	def open(self, port, baud):
		self.ser = serial.Serial(port, baudrate = baud, timeout=self.serial_timeout)
		#self.ser.flushInput()
		self.ser.reset_input_buffer()
		self.ser.reset_output_buffer()
		self.ser.flush()
		self.ser.read_all()

	# Close serial port
	def close(self):
		if self.ser: 
			self.ser.reset_input_buffer()
			self.ser.reset_output_buffer()
			self.ser.flush()
			self.ser.read_all()
			self.ser.close()
		self.sent_cmd = None
		self.ser = None

	# DO NOT CALL THIS DIRECTLY. Use set_cmd
	def __write(self,val):
		cmd = 'AT' if not (val.startswith('AT') or val.startswith('at')) else ''

		dt = (time.time() - self.init_time)
		if self.print_debug: print("TX [{:.2f}]: {}".format(dt, cmd+val))

		cmd = cmd + val + '\r\n'
		cmd = cmd.encode()
		self.ser.write(cmd)
		self.ser.flush()
		self.sent_cmd = time.time()

	# Check is serial port is open
	def isOpen(self):
		return self.ser.isOpen()

	# Wait for modem to respond to AT command sent
	def wait_for_rx(self, wait_time=None, log_file=None, exit_flag = False):
		if wait_time is not None:
			self.msg_timeout = wait_time

		full_rep = []
		while self.sent_cmd or self.send_at and exit_flag != True:
			rep = self.update(log_file)
			if rep is None:
				return full_rep
			elif rep == '':
				time.sleep(0.01)
			else:
				full_rep.append(rep)

		self.msg_timeout = self.msg_timeout_def
		return full_rep

	# Update output/log_file
	def update(self, log_file=None):
		#print("{} {} {} {}".format(time.time(), self.send_at, self.last_rx, self.sent_cmd ))
		if not self.ser.isOpen():
			if self.print_debug: print("Serial port is not open")
			return None

		n = self.ser.inWaiting()
		dt = (time.time() - self.init_time)

		if n > 0:
			self.last_rx = time.time()
			try:
				reply = self.ser.readline()
				reply = reply.decode().strip()
			except:
				return ''

			# URC detection
			#if reply.startswith('+')
			self.parse_urc( reply, log_file)

			if self.sent_cmd:
				if self.print_debug: print("RX [{:.2f}]: {}".format(dt, reply))
				if reply.startswith('OK') or 'ERROR' in reply or 'ABORTED' in reply:
					self.sent_cmd = None
			else:
				if self.print_debug: print("UX [{:.2f}]: {}".format(dt, reply))

			#print('[{:.2f}] {}'.format(dt, reply))
			if log_file: 
				log_file.write('[{:.2f}] '.format(dt))
				log_file.write(reply)
				log_file.write('\r\n')

			#print("have reply: {}".format(reply))
			return reply

		elif self.sent_cmd:
			#print("waiting on send")
			if (time.time() - self.sent_cmd) >= self.msg_timeout:
				if self.print_debug: print("ERROR: timed out waiting for response")
				self.sent_cmd = None
				return 'TIMEOUT'

		# Don't send a new command faster than 200 ms
		elif self.send_at and (time.time() - self.last_rx) >= 0.2 and (time.time() - (self.sent_cmd if self.sent_cmd else 0)) >= .2:
			#print("next send")
			if log_file: 
				log_file.write('[{:.2f}] '.format(dt))
				log_file.write(self.send_at)
				log_file.write('\r\n')

			self.__write(self.send_at)
			self.send_at = None

		return ''

	# Parse URC values we may care about
	def parse_urc(self, rsp, log_file=None):
		#print(f'parse_urc {rsp}')

		# +UUSORD: 0,17
		if '+UUSORD' in rsp:
			val = rsp.rsplit(':', 1)[-1]
			cmd = 'AT+USORD=' + val
			self.__write(cmd)
		elif '+CMT' in rsp:
			# Send SMS ack
			#self.set_cmd('AT+CNMA')
			self.have_sms = True
			self.last_sms = rsp
		elif '+QPING' in rsp:
			# Ping ack
			# +QPING: 0,"8.8.8.8",32,295,255
			# +QPING: 0,1,1,0,295,295,295
			val = rsp.rsplit(':', 1)[-1]
			ms = val.split(',')
			self.ping_count += 1
			if len(ms) > 2 and ms[1].isdigit():
				count = int(ms[1])
				if count + 1 == self.ping_count:
					self.have_ping = True
					self.last_ping = int(ms[-1])
					self.sent_cmd = None
	
	# get sms
	def get_sms(self):
		if self.have_sms:
			self.have_sms = False
			sms = self.last_sms
			self.last_sms = []
			return sms

		return None

	# get ping
	def get_ping(self):
		if self.have_ping:
			self.have_ping = False
			self.ping_count = 0
			ping = self.last_ping
			self.last_ping = []
			return ping

		return None

	# Get the current carrier
	def get_carrier(self, log_file=None):

		# send command
		self.set_cmd('AT+COPS?')

		# wait for response
		reply = self.wait_for_rx(log_file=log_file)

		# parse response
		if reply is not None and len(reply) == 2 and 'OK' in reply[-1]:
			vals = reply[0].split(',')
			if len(vals) >= 3:
				return vals[2]

		return ''
		
	# See if the modem will respond to AT command
	def connected_state(self, log_file=None):

		# send command
		self.set_cmd('AT+CEREG?')

		# wait for response
		reply = self.wait_for_rx(log_file=log_file)

		# parse response
		if reply is not None and len(reply) == 2 and 'OK' in reply[-1]:
			vals = re.findall('[0-9]+', reply[0])
			if len(vals) >= 2:
				try:
					v = int(vals[1])
					return v
				except:
					return 4

		return 4
		

	# Ping a server
	def ping(self, server="8.8.8.8", num=4, log_file=None):

		timeout = 1

		self.have_ping = False
		self.ping_count = 0

		# format command
		cmd = f'AT+QPING=1,"{server}",{timeout},{str(num)}'

		# send command
		self.set_cmd(cmd)

		# wait for response
		
		reply = self.wait_for_rx(wait_time=5, log_file=log_file)
		if reply is None or reply[-1] != 'OK':
			return None
		
		for i in range(20):
			self.update()

			if self.have_ping:
				return self.get_ping()

			time.sleep(.1)

		return None