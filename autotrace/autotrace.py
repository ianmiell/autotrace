from __future__ import unicode_literals
from __future__ import print_function
import argparse
import platform
import os
import sys
import getpass
import logging
import time
import pexpect
import curtsies
from curtsies.fmtfuncs import blue, red, green
from curtsies.input import Input

# TODO: implement help
# TODO: toggle for showing commands in panes, highlight
# TODO: replay function?
#       - add in timer to synchonise time
#       - put elapsed time in before each line
#       - replayer will 'just' read through the output files in the logs 
#       - replayer should therefore take 'replay' and 'logfolder' as an argument
#       - it will work by, for each logfile:
#         - start a autotrace process (because we know autotrace will be installed) that:
#           - reads next line, gobble the time, wait that long and echo the line to stdout
#           - should the first line of the logfile be the command name?

class PexpectSessionManager(object):

	only_one = None

	def __init__(self, logdir=None):
		# Singleton
		assert self.only_one is None
		self.only_one             = True
		self.pexpect_sessions     = []
		self.status               = 'Running'
		self.main_command_session = None
		self.pid                  = os.getpid()
		if logdir is not None:
			assert isinstance(logdir, str)
			self.logdir               = logdir
			os.system('mkdir -p ' + self.logdir)
		else:
			self.logdir               = '/tmp/tmp_autotrace/' + str(self.pid)
			os.system('mkdir -p ' + self.logdir)
			os.system('chmod -R 777 /tmp/tmp_autotrace')
		self.logfilename          = self.logdir + '/manager.autotrace.' + str(self.pid) + '.log'
		self.logfile              = open(self.logfilename,'w+')
		os.chmod(self.logfilename,0o777)
		# Does user have root?
		# TODO: emit warning?
		self.root_ready     = False
		if os.getuid() == 0:
			self.root_ready = True
		# Setup
		self.refresh_window()
		self.start_time           = time.time()


	def refresh_window(self):
		self.window               = curtsies.FullscreenWindow()
		self.screen_arr           = None
		self.wheight              = self.window.height
		self.wwidth               = self.window.width
		# Divide the screen up into two, to keep it simple for now
		self.wheight_top_end	  = int(self.wheight / 2)
		self.wheight_bottom_start = int(self.wheight / 2) + 1
		self.wwidth_left_end	  = int(self.wwidth / 2)
		self.wwidth_right_start   = int(self.wwidth / 2) + 1
		assert self.wheight >= 24, self.quit_autotrace('Terminal not tall enough!')
		assert self.wwidth >= 80, self.quit_autotrace('Terminal not wide enough!')


	def write_to_logfile(self, msg):
		self.logfile.write(self.get_elapsed_time_str() + ' ' + str(msg) + '\n')
		self.logfile.flush()


	def cycle_panes(self):
		# Must have more than 4 panes to do a cycle (including main command)
		num_sessions = len(self.pexpect_sessions)
		if num_sessions <= 4:
			return False
		# eg we have 1, 2, 3, 4, 5
		# cycling:
		#   1 => 5
		#   5 => 4
		#   1 => 3
		#   3 => 2
		#   2 => 1
		max_session_number, _ = self.get_number_of_sessions()
		for session in self.pexpect_sessions:
			if session.session_number not in (3,2,1,0) and max_session_number < int(session.name):
				max_session_number = session.session_number
		assert max_session_number > 0
		for session in self.pexpect_sessions:
			if session.session_number == 3:
				session.session_number = 2
			elif session.session_number == 2:
				session.session_number = 1 
			elif session.session_number == 1:
				session.session_number = str(max_session_number)
			elif session.session_number == 0:
				# Do nothing - this does not get touched
				pass
			else:
				assert isinstance(session.session_number, int), 'Broken session number: ' + session.session_number
				session_number = session.session_number
				if session_number == 1:
					session.session_number = 3
				else:
					session.session_number = str(session_number - 1)


	def get_number_of_sessions(self):
		max_session_number = 0
		reserved_list = (3,2,1,0)
		for session in self.pexpect_sessions:
			if session.session_number not in reserved_list and max_session_number < session.session_number:
				max_session_number = session.session_number
		return max_session_number, max_session_number + len(reserved_list)


	def draw_screen(self, draw_type):
		assert draw_type in ('sessions','help')
		self.screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		# Header
		header_text = 'autotrace running...'
		self.screen_arr[0:1,0:len(header_text)] = [blue(header_text)]
		# Footer
		_, number_of_sessions = self.get_number_of_sessions()
		if number_of_sessions > 0:
			quick_help = 'ESC/q: quit, p: pause, c: continue, m: cycle windows, h: help =>  '
		else:
			quick_help = 'ESC/q: quit, p: pause, c: continue, h: help =>  '
		space =  (self.wwidth - (len(self.status) + len(quick_help)))*' '
		footer_text = self.status + space + quick_help
		self.screen_arr[self.wheight-1:self.wheight,0:len(footer_text)] = [blue(footer_text)]

		if draw_type == 'sessions':
			self.draw_sessions(self.screen_arr)
		elif draw_type == 'help':
			self.draw_help(self.screen_arr)

		# We're done, now render.
		self.window.render_to_terminal(self.screen_arr, cursor_pos=(self.wheight, self.wwidth))


	def draw_help(self, screen_arr):
		help_text_lines = ['Placeholder text',]
		i=2
		for line in help_text_lines:
			self.screen_arr[i:i+1,0:len(line)] = [green(line)]
			i += 1
		


	def draw_sessions(self, screen_arr):
		# Gather sessions
		main_command_session, top_right_session, bottom_left_session, bottom_right_session = (None,)*4
		for session in self.pexpect_sessions:
			if session.session_number == 0:
				main_command_session = session
			elif session.session_number == 3:
				top_right_session = session
			elif session.session_number == 1:
				bottom_left_session = session
			elif session.session_number == 2:
				bottom_right_session = session
		# Validate BEGIN
		assert main_command_session, self.quit_autotrace('Main command session not found in draw_screen')
		assert bottom_left_session, self.quit_autotrace('Bottom left session not found in draw_screen')

		if top_right_session and not bottom_right_session:
			self.quit_autotrace(msg='-t without -r is not allowed. Use -l or -r instead of -t')
		# Validate DONE


		# Helper function to render subwindow - BUGGY?
		# Test with: python autotrace/autotrace.py -l 'ping bing.com' -r 'ping cnn.com' -t 'ping bbc.co.uk' ping google.com
		def render_subwindow(lines, row_range_start, row_range_end, col_range_start, color):
			for i, line in zip(reversed(range(row_range_start,row_range_end)), reversed(lines)):
				self.screen_arr[i:i+1, col_range_start:len(line)] = [color(line)]

		# Split the lines by newline, then reversed and zip up with line 2 to halfway.

		# Top half
		if main_command_session.output != '':
			if top_right_session:
				lines = main_command_session.get_lines(self.wwidth_left_end)
			else:
				lines = main_command_session.get_lines(self.wwidth)
			for i, line in zip(reversed(range(1,self.wheight_top_end)), reversed(lines)):
				self.screen_arr[i:i+1, 0:len(line)] = [green(line)]
		if top_right_session:
			if top_right_session.output != '':
				lines = top_right_session.get_lines(self.wwidth_left_end)
				for i, line in zip(reversed(range(1,self.wheight_top_end)), reversed(lines)):
					self.screen_arr[i:i+1, self.wwidth_right_start:self.wwidth_right_start+len(line)] = [red(line)]

		# Bottom half
		if bottom_left_session.output != '':
			lines = bottom_left_session.get_lines(self.wwidth_left_end)
			for i, line in zip(reversed(range(self.wheight_bottom_start,self.wheight-1)), reversed(lines)):
				self.screen_arr[i:i+1, 0:len(line)] = [red(line)]
		if bottom_right_session:
			if bottom_right_session.output != '':
				lines = bottom_right_session.get_lines(self.wwidth_left_end)
				for i, line in zip(reversed(range(self.wheight_bottom_start,self.wheight-1)), reversed(lines)):
					self.screen_arr[i:i+1, self.wwidth_right_start:self.wwidth_right_start+len(line)] = [red(line)]


	def quit_autotrace(self, msg='All done.'):
		self.screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		self.window.render_to_terminal(self.screen_arr)
		# leave useful message
		msg += '\nLogs and output in: ' + self.logdir
		msg += '\nCommands were: '
		for session in self.pexpect_sessions:
			msg += '\n\t' + session.command
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
				self.quit_autotrace(msg=input_char + ' hit, quitting.')
			elif input_char in (u'p',):
				self.status = 'Paused'
				self.pause_sessions()
				self.draw_screen('sessions')
				for e in input_generator:
					if e == 'c':
						self.unpause_sessions()
						self.status = 'Running'
						self.draw_screen('sessions')
						break
					elif e == 'q':
						self.quit_autotrace()
			elif input_char == 'q':
				self.quit_autotrace()
			elif input_char in (u'm',):
				self.cycle_panes()
				self.draw_screen('sessions')
			elif input_char in (u'h',):
				self.status = 'Help'
				# Default is to pause sessions here - good idea?
				self.pause_sessions()
				self.draw_screen('help')
				for e in input_generator:
					if e == 'c':
						self.unpause_sessions()
						self.status = 'Running'
						self.draw_screen('sessions')
						break
					elif e == 'q':
						self.quit_autotrace()
				# TODO: redraw screen and show help
			elif input_char:
				self.write_to_logfile('input_char')
				self.write_to_logfile(input_char)


	def setup_commands(self, args):
		num_commands = len(args.commands)
		assert num_commands >= 1, self.quit_autotrace('Not enough commands! Must be at least two.')
		bottom_left_command  = None
		bottom_right_command = None
		top_right_command    = None

		main_command         = args.commands[0]
		if num_commands > 1:
			bottom_left_command  = args.commands[1]
		else:
			bottom_left_command  = None
		if num_commands > 2:
			bottom_right_command = args.commands[2]
		if num_commands > 3:
			top_right_command    = args.commands[3]
		remaining_commands = args.commands[3:]
		args = None

		# Main command
		main_session = PexpectSession(main_command, self,0)
		main_session.spawn()
		if top_right_command is None:
			main_session.set_position(0,0,self.wwidth,self.wheight_bottom_start-1)
		else:
			main_session.set_position(0,0,self.wwidth_left_end,self.wheight_bottom_start-1)
			top_right_command = self.replace_pid(top_right_command, str(main_session.pid))
			top_right_session = PexpectSession(top_right_command,self,3)
			top_right_session.set_position(0,self.wwidth_right_start,self.wwidth,self.wheight_bottom_start-1)
		# Default for bottom left is syscall tracer
		if bottom_left_command is None:
			if platform.system() == 'Darwin':
				bottom_left_command = 'dtruss -f -p ' + str(main_session.pid)
			else:
				bottom_left_command = 'strace -tt -f -p ' + str(main_session.pid)
		else:
			bottom_left_command = self.replace_pid(bottom_left_command, str(main_session.pid))
		bottom_left_session = PexpectSession(bottom_left_command,self,1)
		if bottom_right_command is None:
			bottom_left_session.set_position(0,self.wheight_bottom_start,self.wwidth,self.wheight-1)
		else:
			bottom_left_session.set_position(0,self.wheight_bottom_start,self.wwidth_left_end,self.wheight-1)
			bottom_right_command = self.replace_pid(bottom_right_command, str(main_session.pid))
			bottom_right_session = PexpectSession(bottom_right_command,self,2)
			bottom_right_session.set_position(self.wwidth_right_start,self.wheight_bottom_start,self.wwidth,self.wheight-1)

		# Set up any other sessions to be set up.
		count = 0
		for other_command in remaining_commands:
			other_command = self.replace_pid(other_command, str(main_session.pid))
			other_session = PexpectSession(other_command, self, str(count))
			other_session.set_position(0,0,0,0)
			count += 1


	def replace_pid(self, string, pid_str):
		assert isinstance(pid_str, str)
		return string.replace('PID', pid_str)


	def pause_sessions(self):
		for session in self.pexpect_sessions:
			if session.session_number == 0:
				pexpect.run('kill -STOP ' + str(session.pid))
		for session in self.pexpect_sessions:
			if session.session_number != 0:
				pexpect.run('kill -STOP ' + str(session.pid))


	def unpause_sessions(self):
		for session in self.pexpect_sessions:
			if session.session_number != 0:
				pexpect.run('kill -CONT ' + str(session.pid))
		for session in self.pexpect_sessions:
			if session.session_number == 0:
				pexpect.run('kill -CONT ' + str(session.pid))


	def get_elapsed_time_str(self):
		return str(time.time() - self.start_time)




class PexpectSession(object):


	def __init__(self,command, pexpect_session_manager, session_number, encoding='utf-8'):
		self.pexpect_session         = None
		self.session_number          = session_number
		self.command                 = command
		self.output                  = ''
		self.pid                     = -1
		self.encoding                = encoding
		self.pexpect_session_manager = pexpect_session_manager
		self.logfilename             = pexpect_session_manager.logdir + '/' + str(self.session_number) + '.autotrace.' + str(pexpect_session_manager.pid) + '.log'
		self.logfile                 = open(self.logfilename,'w+')
		# Append to sessions
		self.pexpect_session_manager.pexpect_sessions.append(self)
		if self.session_number == 0:
			pexpect_session_manager.main_command_session = self
		self.top_left                = (-1,-1)
		self.bottom_right            = (-1,-1)


	def __str__(self):
		string = ''
		string += '\nsession_number: ' + str(self.session_number)
		string += '\ncommand: ' + str(self.command)
		string += '\npid: ' + str(self.pid)
		return string


	def spawn(self):
		self.pexpect_session         = pexpect.spawn(self.command)
		self.pid                     = self.pexpect_session.pid
		if self.session_number == 0:
			pexpect.run('kill -STOP ' + str(self.pid))




	def write_to_logfile(self, msg):
		self.logfile.write(self.pexpect_session_manager.get_elapsed_time_str() + ' ' + str(msg) + '\n')
		self.logfile.flush()


	def read_line(self,timeout=0.1):
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
		except Exception as eg:
			self.pexpect_session_manager.write_to_logfile('Error in command session: ' + self.command)
			self.pexpect_session_manager.write_to_logfile(eg)
		if string:
			self.write_to_logfile(string.strip())
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

	# TODO: move this functionality into sessionpane
	def set_position(self, top_left_x, top_left_y, bottom_right_x, bottom_right_y):
		self.top_left     = (top_left_x, top_left_y)
		self.bottom_right = (bottom_right_x, bottom_right_y)


# Represents a pane with no concept of context or content.
class SessionPane(object):

	def __init__(self, name):
		self.name                    = name
		self.top_left                = (-1,-1)
		self.bottom_right            = (-1,-1)

	def __str__(self):
		string = ''
		string += '\ntop_left: ' + str(self.top_left)
		string += '\nbottom_right: ' + str(self.bottom_right)
		return string

	def set_position(self, top_left_x, top_left_y, bottom_right_x, bottom_right_y):
		self.top_left     = (top_left_x, top_left_y)
		self.bottom_right = (bottom_right_x, bottom_right_y)


def process_args():
	parser = argparse.ArgumentParser(description='Analyse a process in real time.')
	parser.add_argument('commands', type=str, nargs='?', help='''Commands to autotrace, separated by spaces, eg: "autotrace 'find /' 'strace -p PID' 'vmstat 1'"''')
	parser.add_argument('-l', default=None, help='Folder to log output of commands to.')
	parser.add_argument('-v', default=None, help='Split vertically rather than horizontally.')
	parser.add_argument('--replayfile', help='Replay output of an individual file')
	args = parser.parse_args()
	# Validate BEGIN
	if args.commands is None and args.replayfile is None:
		print('You must supply either a command or a replayfile')
		parser.print_help(sys.stdout)
		sys.ext(1)
	if isinstance(args.commands,str):
		args.commands = [args.commands]
	# Validate DONE
	return args


def main():
	args = process_args()
	if args.replayfile:
		print('replayfile')
	elif args.commands:
		pexpect_session_manager=PexpectSessionManager(args.l)
		# TODO: separate out and determine pane layout
		# TODO: panes then get assigned to sessions before drawing. The
		#       relationship will be that the session will be assigned to at most 1 pane (or None).
		pexpect_session_manager.setup_commands(args)
		main_command_session = None
		for session in pexpect_session_manager.pexpect_sessions:
			print(session)
			if session.session_number == 0:
				main_command_session = session
			else:
				session.spawn()
		assert main_command_session, pexpect_session_manager.quit_autotrace('No main command session set up!')
		pexpect.run('kill -CONT ' + str(main_command_session.pid))
		while True:
			try:
				while True:
					pexpect_session_manager.draw_screen('sessions')
					pexpect_session_manager.handle_sessions()
					pexpect_session_manager.handle_input()
			except KeyboardInterrupt:
				pexpect_session_manager.refresh_window()
	else:
		print('Should not get here 1')
		assert False


autotrace_version='0.0.8'

if __name__ == '__main__':
	main()
