from __future__ import unicode_literals
from __future__ import print_function
import pexpect
import curtsies
import platform
import subprocess
import getpass
import time
import sys
import argparse
from curtsies.fmtfuncs import blue, red, green
from curtsies.formatstring import linesplit
from curtsies.input import *


# TODO: create 'holder' class for all the sessions
class PexpectSession:
	def __init__(self,command,encoding='utf-8'):
		self.command               = command
		self.top_left_position     = -1
		self.bottom_right_position = -1
		self.output                = ''
		self.pexpect_session       = pexpect.spawn(command)
		self.pid                   = self.pexpect_session.pid
		self.encoding              = 'utf-8'

	def read_nonblocking(self,timeout=0.001):
		write_to_logfile('in read_nonblocking for command: ' + self.command)
		if not self.pexpect_session:
			return False
		char = None
		try:
			char = self.pexpect_session.read_nonblocking(timeout=timeout)
		except pexpect.EOF:
			#self.output += '\n--DONE--'
			#self.pexpect_session = None
			pass
		except pexpect.TIMEOUT:
			# This is ok.
			pass
		except:
			self.output += '\nERROR! Unrecognised error in read_nonblocking\n'
		if char:
			self.output += char.decode(self.encoding)
			return True
		return False

	def wrap_output(self, width):
		# TODO
		self.output = self.output
		return True

	def get_lines(self,width):
		self.wrap_output(width)
		return self.output.split('\r\n')


# Set up a logfile for debugging
logfile = open('outfile','w')
def write_to_logfile(msg):
	global logfile
	logfile.write(str(msg) + '\n')
	logfile.flush()


def process_args():
	parser = argparse.ArgumentParser(description='Analyse a process in real time.')
	parser.add_argument('--command', default='ping -c10 google.com')
	return parser.parse_args()

def check_syscall_tracer_ready():
	# If we have sudo, then this returns True, else false.
	if os.getuid() == 0:
		return True, ''
	else:
		# Insist on root for now
		return False, ''
	if os.geteuid() != 0:
		#password = getpass.getpass("[sudo] password: ")
		password = 'N/A'
		return True, password
	return False, ''


def setup_syscall_tracer(command_pexpect_session, sudo_password):
	sudo = """echo '""" + sudo_password + """' | sudo -S """
	sudo = 'sudo '
	if os.getuid() == 0:
		sudo = ''
	this_platform = platform.system()
	if this_platform == 'Darwin':
		command = sudo + 'dtruss -f -p ' + str(command_pexpect_session.pid)
		s = PexpectSession(command)
	else:
		command = sudo + 'strace -f -p ' + str(command_pexpect_session.pid)
		s = PexpectSession(command)
	write_to_logfile(command)
	return s


def main(command):
	input_chars = ''

	res, sudo_password = check_syscall_tracer_ready()
	if not res:
		print('Either become root or make sure sudo is ready to run without password')
		sys.exit(1)

	command_pexpect_session = PexpectSession(command)
	pexpect.run('kill -STOP ' + str(command_pexpect_session.pid))

	strace_pexpect_session = setup_syscall_tracer(command_pexpect_session, sudo_password)
	# Assumes strace exists... need to correct/handle cases where not, eg mac
	# or not installed. Also, what about root? TODO
	pexpect.run('kill -CONT ' + str(command_pexpect_session.pid))

	with curtsies.FullscreenWindow() as window:
		while True:
			# Setup
			wheight = window.height
			wwidth  = window.width
			a = curtsies.FSArray(wheight,wwidth)
			assert wheight >= 24
			assert wwidth >= 80

			# Divide the screen up into two, to keep it simple for now
			wheight_top_end      = int(wheight / 2)
			wheight_bottom_start = int(wheight / 2) + 1
			wwidth_left_end      = int(wwidth / 2)
			wwidth_right_start   = int(wwidth / 2) + 1

			# Header
			header_text = 'telemetrising command: ' + command + ' ' + str(wheight) + 'x' + str(wwidth)
			a[0:1,0:len(header_text)] = [blue(header_text)]

			# Top half for command output
			# Split the lines by newline, then reversed and zip up with line 2 to halfway.
			if command_pexpect_session.output != '':
				lines = command_pexpect_session.get_lines(wwidth)
				# TODO: abstract this
				for i, line in zip(reversed(range(2,wheight_top_end)), reversed(lines)):
					a[i:i+1, 0:len(line)] = [green(line)]

			# Bottom left for strace output
			if strace_pexpect_session.output != '':
				lines = strace_pexpect_session.get_lines(wwidth_left_end)
				# TODO: abstract this
				for i, line in zip(reversed(range(wheight_bottom_start,wheight-2)), reversed(lines)):
					line = line[:50]
					a[i:i+1, 0:len(line)] = [red(line)]

			# Footer
			footer_text = '(x) to do ' + input_chars
			a[wheight-1:wheight,0:len(footer_text)] = [blue(footer_text)]

			# We're done, now render!
			#write_to_logfile(a)
			window.render_to_terminal(a)

			# Now read input from main spawn
			char = None
			# 'while' keeps it line-oriented for reasonable performance...
			seen_output = False
			while not seen_output:
				if command_pexpect_session:
					if command_pexpect_session.read_nonblocking():
						seen_output = True
				if strace_pexpect_session:
					if strace_pexpect_session.read_nonblocking():
						seen_output = True
			#  TODO: slows everything down, make it only check every once in a while
			#with Input() as input_generator:
			#	input_char = input_generator.send(.001)
			#	if input_char:
			#		input_chars += repr(input_char)

if __name__ == '__main__':
	args = process_args()
	main(args.command)
