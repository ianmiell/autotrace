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
import cProfile
import re
from curtsies.fmtfuncs import blue, red, green
from curtsies.formatstring import linesplit
from curtsies.input import *


# TODO: Create logfile for each process, to write output to.
# TODO: When all processes done, quit.
# TODO: create 'holder' class for all the sessions

class PexpectSessionManager:
	only_one = None
	def __init__(self):
		# Singleton
		assert self.only_one is None
		self.only_one         = True
		self.pexpect_sessions = []


class PexpectSession:

	def __init__(self,command,session_manager,encoding='utf-8'):
		self.command               = command
		self.top_left_position     = -1
		self.bottom_right_position = -1
		self.output                = ''
		self.pexpect_session       = pexpect.spawn(command)
		self.pid                   = self.pexpect_session.pid
		self.encoding              = 'utf-8'

	def read_line(self,timeout=0.1):
		if not self.pexpect_session:
			return False
		string = None
		try:
			res = self.pexpect_session.expect('\r\n',timeout=timeout)
			string = self.pexpect_session.before + '\r\n'
		except pexpect.EOF:
			write_to_logfile('Command session: done ' + self.command)
			self.pexpect_session = None
		except pexpect.TIMEOUT:
			# This is ok.
			write_to_logfile('Timeout in command session: ' + self.command)
			pass
		except:
			write_to_logfile('Error in command session: ' + self.command)
		if string:
			self.output += string.decode(self.encoding)
			return True
		return False

	def wrap_output(self, width):
		# TODO
		lines = self.output.split('\r\n')
		#write_to_logfile('width' + str(width))
		#write_to_logfile('lines')
		#write_to_logfile(str(lines))
		lines_new = []
		for line in lines:
			#write_to_logfile('line')
			#write_to_logfile(str(line))
			while len(line) > width-1:
				lines_new.append(line[:width-1])
				line = line[width-1:]
			lines_new.append(line)
		#write_to_logfile('lines_new')
		#write_to_logfile(str(lines_new))
		self.output = '\r\n'.join(lines_new)
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


def setup_syscall_tracer(command_pexpect_session, sudo_password, pexpect_session_manager):
	sudo = """echo '""" + sudo_password + """' | sudo -S """
	sudo = 'sudo '
	if os.getuid() == 0:
		sudo = ''
	this_platform = platform.system()
	if this_platform == 'Darwin':
		command = sudo + 'dtruss -f -p ' + str(command_pexpect_session.pid)
		s = PexpectSession(command,pexpect_session_manager)
	else:
		command = sudo + 'strace -f -p ' + str(command_pexpect_session.pid)
		s = PexpectSession(command,pexpect_session_manager)
	return s


def setup_vmstat_tracer(command_pexpect_session, sudo_password, pexpect_session_manager):
	sudo = 'sudo '
	if os.getuid() == 0:
		sudo = ''
	this_platform = platform.system()
	command = 'vmstat 1 '
	return PexpectSession(command,pexpect_session_manager)


def main(command,pexpect_session_manager):
	input_char = ''

	res, sudo_password = check_syscall_tracer_ready()
	if not res:
		print('Either become root or make sure sudo is ready to run without password')
		sys.exit(1)

	command_pexpect_session = PexpectSession(command,pexpect_session_manager)
	pexpect.run('kill -STOP ' + str(command_pexpect_session.pid))

	strace_pexpect_session = setup_syscall_tracer(command_pexpect_session, sudo_password, pexpect_session_manager)
	vmstat_pexpect_session   = setup_vmstat_tracer(command_pexpect_session, sudo_password, pexpect_session_manager)
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
			wheight_top_end	  = int(wheight / 2)
			wheight_bottom_start = int(wheight / 2) + 1
			wwidth_left_end	  = int(wwidth / 2)
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
					#write_to_logfile(line)
					#write_to_logfile(len(line))
					a[i:i+1, 0:len(line)] = [green(line)]

			# Bottom left for strace output
			if strace_pexpect_session.output != '':
				lines = strace_pexpect_session.get_lines(wwidth_left_end)
				# TODO: abstract this
				for i, line in zip(reversed(range(wheight_bottom_start,wheight-2)), reversed(lines)):
					a[i:i+1, 0:len(line)] = [red(line)]

			# Bottom left for strace output
			if vmstat_pexpect_session.output != '':
				lines = vmstat_pexpect_session.get_lines(wwidth_left_end)
				# TODO: abstract this
				for i, line in zip(reversed(range(wheight_bottom_start,wheight-2)), reversed(lines)):
					a[i:i+1, wwidth_right_start:wwidth_right_start+len(line)] = [red(line)]


			# Footer
			footer_text = '(ESC/q) to quit '
			a[wheight-1:wheight,0:len(footer_text)] = [blue(footer_text)]

			# We're done, now render!
			#write_to_logfile(a)
			window.render_to_terminal(a)

			handle_sessions(command_pexpect_session,strace_pexpect_session,vmstat_pexpect_session)
			handle_input()


def handle_sessions(command_pexpect_session, strace_pexpect_session, vmstat_pexpect_session):
	seen_output = False
	# 'while' keeps it line-oriented for reasonable performance...
	while not seen_output:
		if command_pexpect_session:
			if command_pexpect_session.read_line():
				seen_output = True
		if strace_pexpect_session:
			if strace_pexpect_session.read_line():
				seen_output = True
		if vmstat_pexpect_session:
			if vmstat_pexpect_session.read_line():
				seen_output = True


def handle_input():
	# Handle input
	with Input() as input_generator:
		input_char = input_generator.send(.01)
		if input_char in (u'<ESC>', u'<Ctrl-d>', u'q'):
			sys.exit(0)
		elif input_char:
			write_to_logfile('input_char')
			write_to_logfile(input_char)


if __name__ == '__main__':
	args = process_args()
	pexpect_session_manager=PexpectSessionManager()
	main(args.command,pexpect_session_manager)

