from __future__ import unicode_literals
from __future__ import print_function
import argparse
import platform
import os
import sys
import getpass
import pexpect
import curtsies
from curtsies.fmtfuncs import blue, red, green
from curtsies.input import Input

# TODO: main command is default argument
# TODO: move cursor from top left

class PexpectSessionManager(object):

	only_one = None

	def __init__(self):
		# Singleton
		assert self.only_one is None
		self.only_one             = True
		self.pexpect_sessions     = []
		self.status               = 'Running'
		self.main_command_session = None
		self.pid                  = os.getpid()
		self.tmpdir               = '/tmp/tmp_telemetrise/' + str(self.pid)
		os.system('mkdir -p ' + self.tmpdir)
		self.logfilename          = '/tmp/tmp_telemetrise/' + str(self.pid) + '/manager'
		self.logfile              = open(self.logfilename,'w+')
		os.chmod(self.logfilename,0o777)
		# Does user have root?
		self.root_ready     = False
		if os.getuid() == 0:
			self.root_ready = True
		# Setup
		self.window               = curtsies.FullscreenWindow()
		self.wheight              = self.window.height
		self.wwidth               = self.window.width
		# Divide the screen up into two, to keep it simple for now
		self.wheight_top_end	  = int(self.wheight / 2)
		self.wheight_bottom_start = int(self.wheight / 2) + 1
		self.wwidth_left_end	  = int(self.wwidth / 2)
		self.wwidth_right_start   = int(self.wwidth / 2) + 1
		assert self.wheight >= 24
		assert self.wwidth >= 80


	def write_to_logfile(self, msg):
		self.logfile.write(str(msg) + '\n')
		self.logfile.flush()


	def draw_screen(self):
		# Gather sessions
		main_command_session, top_right_session, bottom_left_command, bottom_right_session = (None,)*4
		for session in self.pexpect_sessions:
			if session.name == 'main_command':
				main_command_session = session
			elif session.name == 'top_right_command':
				top_right_session = session
			elif session.name == 'bottom_left_command':
				bottom_left_session = session
			elif session.name == 'bottom_right_command':
				bottom_right_session = session
		# Validate BEGIN
		assert main_command_session
		assert bottom_left_session

		if top_right_session and not bottom_right_session:
			self.quit_telemetrise(msg='-t without -r is not allowed. Use -l or -r instead of -t')
		# Validate DONE

		window = self.window
		# screen_arr in manager?
		screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		# Header
		header_text = 'telemetrising ...'
		screen_arr[0:1,0:len(header_text)] = [blue(header_text)]

		# Helper function to render subwindow - BUGGY?
		# Test with: python telemetrise/telemetrise.py -l 'ping bing.com' -r 'ping cnn.com' -t 'ping bbc.co.uk' ping google.com
		def render_subwindow(lines, row_range_start, row_range_end, col_range_start, color):
			for i, line in zip(reversed(range(row_range_start,row_range_end)), reversed(lines)):
				screen_arr[i:i+1, col_range_start:len(line)] = [color(line)]

		# Split the lines by newline, then reversed and zip up with line 2 to halfway.

		# Top half
		if main_command_session.output != '':
			if top_right_session:
				lines = main_command_session.get_lines(self.wwidth_left_end)
			else:
				lines = main_command_session.get_lines(self.wwidth)
			for i, line in zip(reversed(range(2,self.wheight_top_end)), reversed(lines)):
				screen_arr[i:i+1, 0:len(line)] = [green(line)]
		if top_right_session:
			if top_right_session.output != '':
				lines = top_right_session.get_lines(self.wwidth_left_end)
				for i, line in zip(reversed(range(2,self.wheight_top_end)), reversed(lines)):
					screen_arr[i:i+1, self.wwidth_right_start:self.wwidth_right_start+len(line)] = [red(line)]

		# Bottom half
		if bottom_left_session.output != '':
			lines = bottom_left_session.get_lines(self.wwidth_left_end)
			for i, line in zip(reversed(range(self.wheight_bottom_start,self.wheight-1)), reversed(lines)):
				screen_arr[i:i+1, 0:len(line)] = [red(line)]
		if bottom_right_session:
			if bottom_right_session.output != '':
				lines = bottom_right_session.get_lines(self.wwidth_left_end)
				for i, line in zip(reversed(range(self.wheight_bottom_start,self.wheight-1)), reversed(lines)):
					screen_arr[i:i+1, self.wwidth_right_start:self.wwidth_right_start+len(line)] = [red(line)]
		# Footer
		quick_help = 'ESC/q to quit, p to pause, c to continue, h for help'
		space =  (self.wwidth - (len(self.status) + len(quick_help)))*' '
		footer_text = self.status + space + quick_help
		screen_arr[self.wheight-1:self.wheight,0:len(footer_text)] = [blue(footer_text)]
		# We're done, now render.
		window.render_to_terminal(screen_arr)


	def quit_telemetrise(self, msg='All done.'):
		screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		self.window.render_to_terminal(screen_arr)
		# TODO: leave useful message
		print(msg)
		sys.exit(0)


	def handle_sessions(self):
		seen_output = False
		while not seen_output:
			for session in self.pexpect_sessions:
				if session.read_line():
					seen_output = True


	def handle_input(self):
		with Input() as input_generator:
			input_char = input_generator.send(.01)
			if input_char in (u'<ESC>', u'<Ctrl-d>', u'q'):
				self.quit_telemetrise(msg=input_char + ' hit, quitting.')
			elif input_char in (u'p',):
				self.status = 'Paused'
				self.pause_sessions()
				self.draw_screen()
				input_char = input_generator
				for e in input_generator:
					if e == 'c':
						self.unpause_sessions()
						self.status = 'Running'
						self.draw_screen()
						break
					if e == 'q':
						quit()
			elif input_char:
				self.write_to_logfile('input_char')
				self.write_to_logfile(input_char)


	def setup_commands(self, args):
		command = ' '.join(args.command)
		this_platform = platform.system()
		# Main command
		main_session = PexpectSession(command, self,'main_command')
		main_session.spawn()
		if args.top_right_command is None:
			main_session.set_position(0,0,self.wwidth,self.wheight_bottom_start-1)
		else:
			main_session.set_position(0,0,self.wwidth_left_end,self.wheight_bottom_start-1)
			top_right_command = args.top_right_command.replace('PID',str(main_session.pid))
			top_right_session = PexpectSession(top_right_command,self,'top_right_command')
			top_right_session.set_position(0,self.wwidth_right_start,self.wwidth,self.wheight_bottom_start-1)
		# Default for bottom left is syscall tracer
		if args.bottom_left_command is None:
			# TODO: use password retrieved elsewhere and add command
			#if self.root_ready:
			#	sudo = ''
			#else:
			#	sudo = 'echo ' + password + ' | sudo -S -n echo && ')
			sudo = ''
			if this_platform == 'Darwin':
				bottom_left_command = sudo + 'dtruss -f -p ' + str(main_session.pid)
			else:
				bottom_left_command = sudo + 'strace -tt -f -p ' + str(main_session.pid)
		else:
			bottom_left_command = args.bottom_left_command.replace('PID',str(main_session.pid))
		bottom_left_session = PexpectSession(bottom_left_command,self,'bottom_left_command')
		if args.bottom_right_command is None:
			bottom_left_session.set_position(0,self.wheight_bottom_start,self.wwidth,self.wheight-1)
		else:
			bottom_left_session.set_position(0,self.wheight_bottom_start,self.wwidth_left_end,self.wheight-1)
			bottom_right_command = args.bottom_right_command.replace('PID',str(main_session.pid))
			bottom_right_session = PexpectSession(bottom_right_command,self,'bottom_right_command')
			bottom_right_session.set_position(self.wwidth_right_start,self.wheight_bottom_start,self.wwidth,self.wheight-1)
		return


	def pause_sessions(self):
		# TODO: handle sudo if needed
		for session in self.pexpect_sessions:
			if session.name == 'main_command':
				pexpect.run('kill -STOP ' + str(session.pid))
		for session in self.pexpect_sessions:
			if session.name != 'main_command':
				pexpect.run('kill -STOP ' + str(session.pid))


	def unpause_sessions(self):
		# TODO: handle sudo if needed
		for session in self.pexpect_sessions:
			if session.name != 'main_command':
				pexpect.run('kill -CONT ' + str(session.pid))
		for session in self.pexpect_sessions:
			if session.name == 'main_command':
				pexpect.run('kill -CONT ' + str(session.pid))




class PexpectSession(object):


	def __init__(self,command, pexpect_session_manager, name, encoding='utf-8'):
		self.pexpect_session         = None
		self.name                    = name
		self.command                 = command
		self.output                  = ''
		self.pid                     = -1
		self.encoding                = encoding
		self.pexpect_session_manager = pexpect_session_manager
		self.top_left                = (-1,-1)
		self.bottom_right            = (-1,-1)
		self.logfilename             = pexpect_session_manager.tmpdir + '/' + name + '.output'
		self.logfile                 = open(self.logfilename,'w+')
		# Append to sessions
		self.pexpect_session_manager.pexpect_sessions.append(self)
		if self.name == 'main_command':
			pexpect_session_manager.main_command_session = self
		if command.strip()[:4] == 'sudo':
			self.needs_root = True
		else:
			self.needs_root              = False
		if self.needs_root and not self.pexpect_session_manager.root_ready:
			make_root_ready()


	def __str__(self):
		string = ''
		string += '\nname: ' + str(self.name)
		string += '\ncommand: ' + str(self.command)
		string += '\npid: ' + str(self.pid)
		string += '\ntop_left: ' + str(self.top_left)
		string += '\nbottom_right: ' + str(self.bottom_right)
		return string


	def spawn(self):
		self.pexpect_session         = pexpect.spawn(self.command)
		self.pid                     = self.pexpect_session.pid
		if self.name == 'main_command':
			pexpect.run('kill -STOP ' + str(self.pid))


	def set_position(self, top_left_x, top_left_y, bottom_right_x, bottom_right_y):
		self.top_left     = (top_left_x, top_left_y)
		self.bottom_right = (bottom_right_x, bottom_right_y)


	def write_to_logfile(self, msg):
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
	parser.add_argument('command', metavar='COMMAND', type=str, nargs='+', help='Command to telemetrise')
	parser.add_argument('-l','--bottom_left_command', default=None, help='Command to run in bottom left. Defaults to syscall tracer')
	parser.add_argument('-r','--bottom_right_command', default=None, help='Command to run in bottom right. If not supplied, -l takes over bottom half.')
	parser.add_argument('-t','--top_right_command', default=None, help='Command to run in top right. If not supplied, COMMAND takes over top half.')
	return parser.parse_args()


def make_root_ready():
	# If we have sudo, then this returns True, else false.
	if os.getuid() == 0:
		return True, ''
	password = getpass.getpass("[sudo] password: ")
	return True, password


def main():
	args = process_args()
	pexpect_session_manager=PexpectSessionManager()
	try:
		pexpect_session_manager.setup_commands(args)
		main_command_session = None
		for session in pexpect_session_manager.pexpect_sessions:
			if session.name == 'main_command':
				main_command_session = session
			else:
				session.spawn()
		assert main_command_session
		pexpect.run('kill -CONT ' + str(main_command_session.pid))
		while True:
			pexpect_session_manager.draw_screen()
			pexpect_session_manager.handle_sessions()
			pexpect_session_manager.handle_input()
	except Exception as e:
		pexpect_session_manager.quit_telemetrise(msg='Exception seen: ' + str(e))


telemetrise_version='0.0.1'

if __name__ == '__main__':
	main()
