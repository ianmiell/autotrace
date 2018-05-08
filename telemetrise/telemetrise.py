from __future__ import unicode_literals
from __future__ import print_function
import argparse
import platform
import os
import sys
import curtsies
import pexpect
from curtsies.fmtfuncs import blue, red, green
from curtsies.input import Input


# TODO: When all processes done, quit.
# TODO: create 'holder' class for all the sessions and cycle through
# TODO: make session command optional, with PID as a placeholder

class PexpectSessionManager:

	only_one = None

	def __init__(self, logfile='outfile'):
		# Singleton
		assert self.only_one is None
		self.only_one             = True
		self.pexpect_sessions     = []
		self.status               = 'Running'
		self.main_command_session = None
		# TODO: logfile: put in code dir ../logs
		self.logfile              = open(logfile,'w+')
		os.chmod(logfile,0o777)

	def write_to_logfile(self, msg):
		self.logfile.write(str(msg) + '\n')
		self.logfile.flush()

	


class PexpectSession:

	def __init__(self,command, pexpect_session_manager, name, logfile='outfile', encoding='utf-8'):
		self.name                    = name
		self.command                 = command
		self.top_left_position       = -1
		self.bottom_right_position   = -1
		self.output                  = ''
		self.pexpect_session         = pexpect.spawn(command)
		self.pid                     = self.pexpect_session.pid
		self.encoding                = 'utf-8'
		self.pexpect_session_manager = pexpect_session_manager
		self.top_left                = (-1,-1)
		self.bottom_right            = (-1,-1)
		self.logfile                 = open(logfile + '_' + name + '.output','w+')
		# Append to sessions
		self.pexpect_session_manager.pexpect_sessions.append(self.pexpect_session)
		if self.name == 'main_command':
			pexpect_session_manager.main_command_session = self

	def set_position(self, top_left_x, top_left_y, bottom_right_x, bottom_right_y):
		self.top_left     = (top_left_x, top_left_y)
		self.bottom_right = (bottom_right_x, bottom_right_y)

	def write_to_logfile(self):
		self.logfile.write(str(msg) + '\n')
		self.logfile.flush()

	def read_line(self,timeout=0.1):
		assert self.top_left     != (-1,-1)
		assert self.bottom_right != (-1,-1)
		if not self.pexpect_session:
			return False
		string = None
		try:
			self.pexpect_session.expect('\r\n',timeout=timeout)
			string = self.pexpect_session.before.decode(self.encoding) + '\r\n'
		except pexpect.EOF:
			self.pexpect_session_manager.write_to_logfile('Command session: done ' + self.command)
			self.pexpect_session = None
		except pexpect.TIMEOUT:
			# This is ok.
			self.pexpect_session_manager.write_to_logfile('Timeout in command session: ' + self.command)
			pass
		except Exception as e:
			self.pexpect_session_manager.write_to_logfile('Error in command session: ' + self.command)
			self.pexpect_session_manager.write_to_logfile(e)
		if string:
			self.output += string
			return True
		return False

	def wrap_output(self, width):
		lines = self.output.split('\r\n')
		lines_new = []
		for line in lines:
			while len(line) > width-1:
				lines_new.append(line[:width-1])
				line = line[width-1:]
			lines_new.append(line)
		self.output = '\r\n'.join(lines_new)
		return True

	def get_lines(self,width):
		self.wrap_output(width)
		return self.output.split('\r\n')




def process_args():
	parser = argparse.ArgumentParser(description='Analyse a process in real time.')
	parser.add_argument('--command', default='ping -c10 google.com')
	return parser.parse_args()

def check_syscall_tracer_ready():
	# If we have sudo, then this returns True, else false.
	if os.getuid() == 0:
		return True, ''
	# Insist on root for now
	return False, ''
	#if os.geteuid() != 0:
	#	#password = getpass.getpass("[sudo] password: ")
	#	password = 'N/A'
	#	return True, password
	#return False, ''


def setup_syscall_tracer(command_pexpect_session, sudo_password, pexpect_session_manager):
	sudo = """echo '""" + sudo_password + """' | sudo -S """
	sudo = 'sudo '
	if os.getuid() == 0:
		sudo = ''
	this_platform = platform.system()
	if this_platform == 'Darwin':
		command = sudo + 'dtruss -f -p ' + str(command_pexpect_session.pid)
		s = PexpectSession(command,pexpect_session_manager,'syscall_command')
	else:
		command = sudo + 'strace -ttt -f -p ' + str(command_pexpect_session.pid)
		s = PexpectSession(command,pexpect_session_manager,'syscall_command')
	return s


def setup_vmstat_tracer(pexpect_session_manager):
	this_platform = platform.system()
	if this_platform == 'Darwin':
		command = 'iostat 1 '
	else:
		command = 'vmstat 1 '
	return PexpectSession(command,pexpect_session_manager,'vmstat_command')


def main(command,pexpect_session_manager):

	res, sudo_password = check_syscall_tracer_ready()
	if not res:
		print('Either become root or make sure sudo is ready to run without password')
		sys.exit(1)

	command_pexpect_session = PexpectSession(command,pexpect_session_manager,'main_command')
	pexpect.run('kill -STOP ' + str(command_pexpect_session.pid))

	strace_pexpect_session = setup_syscall_tracer(command_pexpect_session, sudo_password, pexpect_session_manager)
	vmstat_pexpect_session = setup_vmstat_tracer(pexpect_session_manager)
	pexpect.run('kill -CONT ' + str(command_pexpect_session.pid))

	with curtsies.FullscreenWindow() as window:
		while True:
			build_page(window, pexpect_session_manager, command_pexpect_session, strace_pexpect_session, vmstat_pexpect_session)
			handle_sessions(command_pexpect_session,strace_pexpect_session,vmstat_pexpect_session)
			handle_input(pexpect_session_manager)


# TODO simplify build_page
def build_page(window, pexpect_session_manager, command_pexpect_session, strace_pexpect_session, vmstat_pexpect_session):
	# Setup
	wheight    = window.height
	wwidth     = window.width
	screen_arr = curtsies.FSArray(wheight,wwidth)
	assert wheight >= 24
	assert wwidth >= 80
	command = pexpect_session_manager.main_command_session.command

	# Divide the screen up into two, to keep it simple for now
	wheight_top_end	     = int(wheight / 2)
	wheight_bottom_start = int(wheight / 2) + 1
	wwidth_left_end	     = int(wwidth / 2)
	wwidth_right_start   = int(wwidth / 2) + 1

	# Header
	header_text = 'telemetrising command: ' + command + ' ' + str(wheight) + 'x' + str(wwidth)
	screen_arr[0:1,0:len(header_text)] = [blue(header_text)]

	# Top half for command output
	# Split the lines by newline, then reversed and zip up with line 2 to halfway.
	command_pexpect_session.set_position(0,0,wwidth,wheight_bottom_start-1)
	if command_pexpect_session.output != '':
		lines = command_pexpect_session.get_lines(wwidth)
		# TODO: abstract this
		for i, line in zip(reversed(range(2,wheight_top_end)), reversed(lines)):
			screen_arr[i:i+1, 0:len(line)] = [green(line)]

	# Bottom left for strace output
	strace_pexpect_session.set_position(0,wheight_bottom_start,wwidth_left_end,wheight-1)
	if strace_pexpect_session.output != '':
		lines = strace_pexpect_session.get_lines(wwidth_left_end)
		# TODO: abstract this
		for i, line in zip(reversed(range(wheight_bottom_start,wheight-1)), reversed(lines)):
			screen_arr[i:i+1, 0:len(line)] = [red(line)]

	# Bottom right for vmstat output
	vmstat_pexpect_session.set_position(wwidth_right_start,wheight_bottom_start,wwidth,wheight-1)
	if vmstat_pexpect_session.output != '':
		lines = vmstat_pexpect_session.get_lines(wwidth_left_end)
		# TODO: abstract this
		for i, line in zip(reversed(range(wheight_bottom_start,wheight-1)), reversed(lines)):
			screen_arr[i:i+1, wwidth_right_start:wwidth_right_start+len(line)] = [red(line)]

	# Footer
	quick_help = 'ESC/q to quit, p to pause, c to continue, h for help'
	space =  (wwidth - (len(pexpect_session_manager.status) + len(quick_help)))*' '

	footer_text = pexpect_session_manager.status + space + quick_help
	screen_arr[wheight-1:wheight,0:len(footer_text)] = [blue(footer_text)]

	# We're done, now render!
	window.render_to_terminal(screen_arr)



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


def handle_input(pexpect_session_manager):
	# Handle input
	with Input() as input_generator:
		input_char = input_generator.send(.01)
		if input_char in (u'<ESC>', u'<Ctrl-d>', u'q'):
			quit()
		elif input_char in (u'p',):
			pexpect_session_manager.status = 'Paused'
			input_char = input_generator
			for e in input_generator:
				if e == 'c':
					pexpect_session_manager.status = 'Running'
					break
				if e == 'q':
					quit()
		elif input_char:
			pexpect_session_manager.write_to_logfile('input_char')
			pexpect_session_manager.write_to_logfile(input_char)

def quit(msg=''):
	# TODO: close window, leave useful message
	sys.exit(0)

def run():
	args = process_args()
	pexpect_session_manager=PexpectSessionManager()
	main(args.command,pexpect_session_manager)

telemetrise_version='0.0.1'


if __name__ == '__main__':
	run()
