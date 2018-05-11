from __future__ import unicode_literals
from __future__ import print_function
import argparse
import platform
import os
import sys
import time
import pexpect
import curtsies
from curtsies.fmtfuncs import blue, red, green
from curtsies.input import Input

# TODO: implement help
# TODO: toggle for showing commands in panes, highlight
# TODO: default to 'strace the last thing you ran'? ps aux --sort +start_time | tail -n 4 | awk 'NR==1{print $2}'
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
	# Singleton
	only_one = None
	def __init__(self, logdir=None, debug=False):
		assert self.only_one is None
		self.only_one             = True
		self.debug                = debug
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
		self.screen_arr           = None

	def __str__(self):
		string = ''
		string += '\nwheight: ' + str(self.wheight)
		string += '\nwwidth: ' + str(self.wwidth)
		return string

	def debug_msg(self, msg,pause=None):
		if self.debug:
			print(msg)
		if pause:
			time.sleep(pause)

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
		for session in self.pexpect_sessions:
			print(session)
		sys.exit(1)
		num_sessions = len(self.pexpect_sessions)
		if num_sessions <= 4:
			return False
		# eg we have 1, 2, 3, 4, 5
		# cycling: #   1 => 5 #   5 => 4 #   1 => 3 #   3 => 2 #   2 => 1
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
		reserved_list = (0,1,2,3)
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
			self.draw_sessions()
		elif draw_type == 'help':
			self.draw_help()
		if not self.debug:
			# We're done, now render.
			self.window.render_to_terminal(self.screen_arr, cursor_pos=(self.wheight, self.wwidth))

	def draw_sessions(self):
		# Gather sessions
		main_command_session, session_3, session_1, session_2 = (None,)*4
		for session in self.pexpect_sessions:
			if session.session_number == 0:
				main_command_session = session
			elif session.session_number == 3:
				session_3 = session
			elif session.session_number == 1:
				session_1 = session
			elif session.session_number == 2:
				session_2 = session
		# Validate BEGIN
		assert main_command_session, self.quit_autotrace('Main command session not found in draw_screen')
		assert session_1, self.quit_autotrace('Bottom left session not found in draw_screen')
		if session_3 and not session_2:
			self.quit_autotrace(msg='-t without -r is not allowed. Use -l or -r instead of -t')
		# Validate DONE

		# Main session
		if main_command_session.output != '':
			pane = main_command_session.session_pane
			pane_width = pane.get_width()
			lines = main_command_session.get_lines(pane_width)
			for i, line in zip(reversed(range(pane.top_left_y,pane.bottom_right_y)), reversed(lines)):
				self.screen_arr[i:i+1, pane.top_left_x:pane.top_left_x+len(line)] = [green(line)]
		if session_3 and session_3.output != '':
			pane = session_3.session_pane
			lines = session_3.get_lines(pane.get_width())
			for i, line in zip(reversed(range(pane.top_left_y,pane.bottom_right_y)), reversed(lines)):
				self.screen_arr[i:i+1, pane.top_left_x:pane.top_left_x+len(line)] = [red(line)]

		# Main tracer
		if session_1.output != '':
			pane = session_1.session_pane
			lines = session_1.get_lines(pane.get_width())
			for i, line in zip(reversed(range(pane.top_left_y,pane.bottom_right_y)), reversed(lines)):
				self.screen_arr[i:i+1, pane.top_left_x:pane.top_left_x+len(line)] = [red(line)]
		if session_2:
			if session_2.output != '':
				pane = session_2.session_pane
				lines = session_2.get_lines(pane.get_width())
				for i, line in zip(reversed(range(pane.top_left_y,pane.bottom_right_y)), reversed(lines)):
					self.screen_arr[i:i+1, pane.top_left_x:pane.top_left_x+len(line)] = [red(line)]

	def draw_help(self):
		help_text_lines = ['Placeholder text',]
		i=2
		for line in help_text_lines:
			self.screen_arr[i:i+1,0:len(line)] = [green(line)]
			i += 1

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


	# Handles initial placement of sessions and panes.
	def initialize_commands(self, args):
		num_commands = len(args.commands)
		assert num_commands >= 1, self.quit_autotrace('Not enough commands! Must be at least two.')
		session_1_command = None
		session_2_command = None
		session_3_command = None

		main_command         = args.commands[0]
		if num_commands > 1:
			session_1_command  = args.commands[1]
		else:
			session_1_command  = None
		if num_commands > 2:
			session_2_command = args.commands[2]
		if num_commands > 3:
			session_3_command    = args.commands[3]
		remaining_commands = args.commands[3:]
		vertically_split = args.v
		assert not args.v or session_2_command is None, 'BUG! Vertical arg should be off at this point if session_2 exists'
		args = None

		# Main command setup
		main_session = PexpectSession(main_command, self, 0, pane_name='top_left')
		main_session.spawn()
		if session_3_command is None:
			if vertically_split:
				main_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight-1)
			else:
				main_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight_bottom_start-1)
		else:
			# At least 3 sessions
			main_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight_bottom_start-1)
			# Session 3 setup
			session_3_command = replace_pid(session_3_command, str(main_session.pid))
			session_3 = PexpectSession(session_3_command, self, 3, 'top_right')
			session_3.session_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight_bottom_start-1)
		# Session 1 setup
		# Default tracer is a syscall tracer
		if session_1_command is None:
			if platform.system() == 'Darwin':
				session_1_command = 'dtruss -f -p ' + str(main_session.pid)
			else:
				session_1_command = 'strace -tt -f -p ' + str(main_session.pid)
		else:
			session_1_command = replace_pid(session_1_command, str(main_session.pid))
		session_1 = PexpectSession(session_1_command, self, 1, pane_name='bottom_left')
		if session_2_command is None:
			# Two panes only
			if vertically_split:
				session_1.session_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=0, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)
			else:
				session_1.session_pane.set_position(top_left_x=0, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)
		else:
			session_1.session_pane.set_position(top_left_x=0, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight-1)
			session_2_command = replace_pid(session_2_command, str(main_session.pid))
			session_2 = PexpectSession(session_2_command, self, 2, pane_name='bottom_right')
			session_2.session_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)

		# Set up any other sessions to be set up with no panes.
		count = 4
		for other_command in remaining_commands:
			other_command = replace_pid(other_command, str(main_session.pid))
			other_session = PexpectSession(other_command, self, count)
			self.pexpect_sessions.append(other_session)
			count += 1


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

	def debug_screen_array(self, screen_arr):
		# TODO make this work?
		x, y = 0, 0
		self.pexpect_sessions[0].write_to_logfile('==========DEBUG SCREEN ARRAY============')
		self.pexpect_sessions[0].write_to_logfile('height: ' + str(screen_arr.height))
		self.pexpect_sessions[0].write_to_logfile('width: ' + str(screen_arr.width))
		while y < screen_arr.height:
			line = ''
			while x < screen_arr.width:
				c=screen_arr[x,y]
				if isinstance(c,str) and ord(c) < 128:
					if c == ' ':
						line += '.'
					else:
						line += c
				else:
					pass
				x += 1
			self.pexpect_sessions[0].write_to_logfile('line: ' + str(y) + line)
			y += 1
		self.pexpect_sessions[0].write_to_logfile('==========DEBUG SCREEN ARRAY END============')


class PexpectSession(object):

	def __init__(self, command, pexpect_session_manager, session_number, pane_name=None, encoding='utf-8'):
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
		if pane_name:
			self.session_pane            = SessionPane(pane_name)
			self.session_pane.top_left   = (-1,-1)
			self.session_pane.bottom_right            = (-1,-1)
		else:
			self.session_pane            = None
		assert isinstance(self.session_number, int)

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


# Represents a pane with no concept of context or content.
class SessionPane(object):

	def __init__(self, name):
		self.name                    = name
		self.top_left_x              = -1
		self.top_left_y              = -1
		self.bottom_right_x          = -1
		self.bottom_right_y          = -1

	def __str__(self):
		string = ''
		string += '\nname: '           + str(self.name)
		string += '\ntop_left_x: '     + str(self.top_left_x)
		string += '\ntop_left_y: '     + str(self.top_left_y)
		string += '\nbottom_right_x: ' + str(self.bottom_right_x)
		string += '\nbottom_right_y: ' + str(self.bottom_right_y)
		string += '\nwidth: '          + str(self.get_width())
		return string

	def set_position(self, top_left_x, top_left_y, bottom_right_x, bottom_right_y):
		self.top_left_x     = top_left_x
		self.top_left_y     = top_left_y
		self.bottom_right_x = bottom_right_x
		self.bottom_right_y = bottom_right_y

	def get_width(self):
		return self.bottom_right_x - self.top_left_x


def process_args():
	parser = argparse.ArgumentParser(description='Analyse a process in real time.')
	parser.add_argument('commands', type=str, nargs='*', help='''Commands to autotrace, separated by spaces, eg: "autotrace 'find /' 'strace -p PID' 'vmstat 1'"''')
	parser.add_argument('-l', default=None, help='Folder to log output of commands to.')
	parser.add_argument('-v', action='store_const', const=True, default=None, help='Split vertically rather than horizontally (the default).')
	parser.add_argument('-d', action='store_const', const=True, default=None, help='Debug mode')
	parser.add_argument('--replayfile', help='Replay output of an individual file')
	args = parser.parse_args()
	# Validate BEGIN
	if args.commands == [] and args.replayfile is None:
		print('You must supply either a command or a replayfile')
		parser.print_help(sys.stdout)
		sys.exit(1)
	if isinstance(args.commands,str):
		args.commands = [args.commands]
	if args.v and len(args.commands) > 2:
		print('-v and more than two commands supplied. -v does not make sense, so dropping that arg.')
		args.v = False
		time.sleep(1)
	return args


def replace_pid(string, pid_str):
	assert isinstance(pid_str, str)
	return string.replace('PID', pid_str)


def main():
	args = process_args()
	if args.replayfile:
		print('replayfile')
	elif args.commands:
		pexpect_session_manager=PexpectSessionManager(args.l, debug=args.d)
		pexpect_session_manager.initialize_commands(args)
		main_command_session = None
		for session in pexpect_session_manager.pexpect_sessions:
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


autotrace_version='0.0.8'
if __name__ == '__main__':
	main()
