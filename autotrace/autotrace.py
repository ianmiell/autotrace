from __future__ import unicode_literals
from __future__ import print_function
import argparse
import platform
import os
import sys
import time
import pexpect
import curtsies
from curtsies.fmtfuncs import black, yellow, magenta, cyan, gray, blue, red, green, on_black, on_dark, on_red, on_green, on_yellow, on_blue, on_magenta, on_cyan, on_gray, bold, dark, underline, blink, invert, plain
from curtsies.input import Input

PY3 = sys.version_info[0] >= 3
if PY3:
	unicode = str

# TODO: implement help
# TODO: status bar per pane, toggle for showing commands in panes, highlight
# TODO: remove cursor (how?)
# TODO: replay function?
#       - put elapsed time in before each line
#       - replayer will 'just' read through the output files in the logs
#       - replayer should therefore take 'replay' and 'logfolder' as an argument
#       - it will work by, for each logfile:
#         - start a autotrace process (because we know autotrace will be installed) that:
#           - reads next line, gobble the time and the type, wait that long and echo the line to stdout
#           - should the first line of the logfile be the command name?

class PexpectSessionManager(object):
	# Singleton
	only_one = None
	def __init__(self, logdir=None, debug=False, encoding='utf-8'):
		assert self.only_one is None
		self.only_one             = True
		self.debug                = debug
		self.pexpect_sessions     = []
		self.status               = 'Running'
		self.status_message       = ''
		self.main_command_session = None
		self.pid                  = os.getpid()
		self.timeout_delay        = 0.001
		self.encoding             = encoding
		self.zoomed_session       = None
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
		# TODO: emit warning if not root?
		self.root_ready     = False
		if os.getuid() == 0:
			self.root_ready = True
		# Setup
		self.refresh_window()
		self.start_time            = time.time()
		self.paused_total_time     = 0.0 # TODO: start and stop paused timer on start and stop pause.
		self.screen_arr            = None
		self.vertically_split      = False

	def __str__(self):
		string =  '\n============= SESSION MANAGER OBJECT BEGIN ==================='
		string += '\nwheight: ' + str(self.wheight)
		string += '\nwwidth: ' + str(self.wwidth)
		for session in self.pexpect_sessions:
			string += str(session)
		string += '\n============= SESSION MANAGER OBJECT END   ==================='
		return string

	def debug_msg(self, msg,pause=None):
		if self.debug:
			print(msg)
		else:
			self.write_to_manager_logfile('DEBUG MESSAGE:\n' + msg)
		if pause:
			time.sleep(pause)

	def refresh_window(self):
		self.window               = curtsies.FullscreenWindow(hide_cursor=True)
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

	def write_to_manager_logfile(self, msg):
		self.logfile.write(self.get_elapsed_time_str() + ' ' + str(msg) + '\n')
		self.logfile.flush()

	def cycle_panes(self):
		# Must have more than 4 panes to do a cycle (including main command)
		if len(self.pexpect_sessions) <= 4:
			return False
		# eg we have 1, 2, 3, 4, 5
		# cycling: #   1 => 5 #   5 => 4 #   1 => 3 #   3 => 2 #   2 => 1
		# Get the pane of session number (using function get_pane_by_session_number)
		# then actually move the pane objects around.
		new_panes = {}
		for session in self.pexpect_sessions:
			if session.session_number == 0:
				pass # Do nothing - this does not get touched
			elif session.session_number == 1:
				new_panes.update({session.session_number:self.get_pane_by_session_number(len(self.pexpect_sessions) - 1)})
			else:
				new_panes.update({session.session_number:self.get_pane_by_session_number(session.session_number - 1)})
		for session in self.pexpect_sessions:
			if session.session_number != 0:
				session.session_pane = new_panes[session.session_number]
		new_panes = None

	def draw_screen(self, draw_type, quick_help):
		assert draw_type in ('sessions','help')
		self.screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		# Header
		header_text = 'Autotrace state: ' + self.status + ' ... ' + self.status_message
		self.screen_arr[0:1,0:len(header_text)] = [blue(header_text)]
		# Footer
		space =  (self.wwidth - (len(self.status) + len(quick_help)))*' '
		footer_text = self.status + space + quick_help
		self.screen_arr[self.wheight-1:self.wheight,0:len(footer_text)] = [blue(footer_text)]
		# Draw the sessions.
		if draw_type == 'sessions':
			# Is there a zoomed session? Just write that one out.
			if self.zoomed_session:
				self.do_layout('zoomed')
				self.zoomed_session.write_out_session_to_fit_pane()
			else:
				self.do_layout('default')
				for session in self.pexpect_sessions:
					session.write_out_session_to_fit_pane()
		elif draw_type == 'help':
			self.draw_help()
		if not self.debug:
			self.window.render_to_terminal(self.screen_arr, cursor_pos=(self.wheight, self.wwidth))

	def draw_help(self):
		help_text_lines = self.get_state_for_user().split('\n')
		i=2
		for line in help_text_lines:
			self.screen_arr[i:i+1,0:len(line)] = [green(line)]
			i += 1

	def quit_autotrace(self, msg='All done.'):
		self.screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		self.window.render_to_terminal(self.screen_arr)
		print(msg + self.get_state_for_user())
		sys.exit(0)

	def get_state_for_user(self):
		# leave useful message
		msg = '\nLogs and output in: ' + self.logdir
		msg += '\nCommands were: '
		for session in self.pexpect_sessions:
			msg += '\n\t' + session.command
		return msg

	def handle_sessions(self):
		seen_output = False
		lines_seen = {}
		while not seen_output:
			for session in self.pexpect_sessions:
				lines_seen.update({session:False})
				if session.read_line():
					seen_output = True
					lines_seen.update({session:True})
		# Determine which ones saw output.
		# The ones that did not need to 'fake read' a line of type 'display_sync_line'
		assert seen_output
		for session in self.pexpect_sessions:
			if not lines_seen[session]:
				session.append_output_line('','display_sync_line')

	def get_quick_help(self):
		if self.status == 'Running':
			number_of_sessions = len(self.pexpect_sessions)
			zoom_str = ''
			for i in range(0,number_of_sessions):
				if i > 0:
					zoom_str += ',' + str(i)
				else:
					zoom_str += str(i)
			if number_of_sessions > 4:
				quick_help = 'ESC/q: quit, p: pause, c: continue, m: cycle windows, ' + zoom_str + ': zoom, z: zoom out, h: help =>  '
			else:
				quick_help = 'ESC/q: quit, p: pause, c: continue, ' + zoom_str + ' zoom, z: zoom out, h: help =>  '
		elif self.status == 'Paused':
			quick_help = 'ESC/q: quit, c: continue running, f: page forward, b: page back =>  '
		elif self.status == 'Help':
			quick_help = 'c: continue running =>  '
		return quick_help


	def handle_input(self):
		quick_help = self.get_quick_help()
		quit_chars = (u'<ESC>', u'<Ctrl-d>', u'q')
		with Input() as input_generator:
			input_char = input_generator.send(self.timeout_delay)
			if input_char:
				self.write_to_manager_logfile('input_char: ' + input_char)
			if input_char in quit_chars:
				self.quit_autotrace(msg=input_char + ' hit, quitting.')
			elif input_char in (u'm',):
				self.cycle_panes()
				self.draw_screen('sessions',quick_help=self.get_quick_help())
			elif input_char in (u'z',):
				# Revert layout status from zoomed
				self.zoomed_session = None
				self.draw_screen('sessions',quick_help=self.get_quick_help())
			elif input_char in [str(x) for x in range(0,len(self.pexpect_sessions))]:
				# Set session as zoomed.
				for session in self.pexpect_sessions:
					if session.session_number == int(input_char):
						self.zoomed_session = session
				# Redraw screen
				self.draw_screen('sessions',quick_help=self.get_quick_help())
			elif input_char in (u'p',):
				# Handle paused state
				self.status = 'Paused'
				self.pause_sessions()
				self.draw_screen('sessions',quick_help=self.get_quick_help())
				for e in input_generator:
					if input_char in quit_chars:
						self.quit_autotrace()
					elif e == 'c':
						self.move_panes_to_tail()
						self.unpause_sessions()
						self.status = 'Running'
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						break
					elif e == 'b':
						msg = self.scroll_back()
						self.status_message = 'you just hit back ' + msg
						self.draw_screen('sessions',quick_help=self.get_quick_help())
					elif e == 'f':
						msg = self.scroll_forward()
						self.status_message = 'you just hit forward ' + msg
						self.draw_screen('sessions',quick_help=self.get_quick_help())
					else:
						self.write_to_manager_logfile('input_char: ' + input_char)
			elif input_char in (u'h',):
				quick_help = 'ESC/q: quit, c: continue running =>  '
				# Handle help state
				self.status = 'Help'
				# Default is to pause sessions here - good idea?
				self.pause_sessions()
				self.draw_screen('help',quick_help=self.get_quick_help())
				for e in input_generator:
					if e in quit_chars:
						# TODO: maybe go back to running from here?
						self.quit_autotrace()
					elif e == 'c':
						self.unpause_sessions()
						self.status = 'Running'
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						break
					else:
						self.write_to_manager_logfile('input_char: ' + input_char)


	# Handles initial placement of sessions and panes.
	def initialize_commands(self, args):
		num_commands = len(args.commands)
		assert num_commands >= 1, self.quit_autotrace('Not enough commands! Must be at least two.')
		session_1_command     = None
		session_2_command     = None
		session_3_command     = None
		main_command          = args.commands[0]
		if num_commands > 1:
			session_1_command = args.commands[1]
		else:
			session_1_command = None
		if num_commands > 2:
			session_2_command = args.commands[2]
		if num_commands > 3:
			session_3_command = args.commands[3]
		remaining_commands    = args.commands[4:]
		self.vertically_split = args.v
		logtimestep           = args.logtimestep
		assert not args.v or session_2_command is None, 'BUG! Vertical arg should be off at this point if session_2 exists'
		args = None
		# Args, collected, set up commands and sessions

		# Setup command information, and keep a count of sessions
		session_count = 0
		main_session = PexpectSession(main_command, self, session_count, pane_name='top_left', pane_color=green, logtimestep=logtimestep)
		main_session.spawn()
		session_count += 1
		if session_1_command is None:
			if platform.system() == 'Darwin':
				session_1_command = 'dtruss -f -p ' + str(main_session.pid)
			else:
				session_1_command = 'strace -tt -f -p ' + str(main_session.pid)
		else:
			session_1_command = replace_pid(session_1_command, str(main_session.pid))
		PexpectSession(session_1_command, self, session_count, pane_name='bottom_left', logtimestep=logtimestep)
		session_count += 1
		if session_2_command is not None:
			session_2_command = replace_pid(session_2_command, str(main_session.pid))
			PexpectSession(session_2_command, self, session_count, pane_name='bottom_right', logtimestep=logtimestep)
			session_count += 1
		if session_3_command is not None:
			session_3_command = replace_pid(session_3_command, str(main_session.pid))
			PexpectSession(session_3_command, self, session_count, 'top_right', logtimestep=logtimestep)
			session_count += 1
		# Set up any other sessions to be set up with no panes.
		for other_command in remaining_commands:
			other_command = replace_pid(other_command, str(main_session.pid))
			PexpectSession(other_command, self, session_count, logtimestep=logtimestep)
			session_count += 1
		self.do_layout('default')


	def do_layout(self, layout):
		assert isinstance(layout, unicode), 'layout is of type: ' + str(type(layout))
		if layout == 'default':
			self.do_layout_default()
		elif layout == 'zoomed':
			self.do_layout_zoomed()
		else:
			assert False, 'do_layout: ' + layout + ' not handled'


	def do_layout_zoomed(self):
		assert self.zoomed_session
		# TODO: which session is zoomed? Give that one the whole screen
		zoomed_session = None
		for session in self.pexpect_sessions:
			if session == self.zoomed_session:
				zoomed_session = session
				break
		assert zoomed_session
		zoomed_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)


	def do_layout_default(self):
		main_session      = None
		session_1         = None
		session_2         = None
		session_3         = None
		for session in self.pexpect_sessions:
			if session.session_number == 0:
				main_session = session
			elif session.session_number == 1:
				session_1    = session
			elif session.session_number == 2:
				session_2    = session
			elif session.session_number == 3:
				session_3    = session
		assert main_session is not None and session_1 is not None

		if session_3 is None:
			# Two panes only, so are we vertically split?
			if self.vertically_split:
				main_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight-1)
			else:
				main_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight_bottom_start-1)
		else:
			# At least 3 sessions (4 including main), so set up main session in top left...
			main_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight_bottom_start-1)
			# ... and then session 3 setup in top right.
			session_3.session_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight_bottom_start-1)
		if session_2 is None:
			# Two panes only, so are we vertically split?
			if self.vertically_split:
				session_1.session_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=0, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)
			else:
				session_1.session_pane.set_position(top_left_x=0, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)
		else:
			# At least 2 sessions (3 including main), so set up second session in bottom left...
			session_1.session_pane.set_position(top_left_x=0, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight-1)
			# ... and then session 3 in bottom right.
			session_2.session_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)


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
	def get_elapsed_time(self):
		return time.time() - self.start_time

	def debug_screen_array(self, screen_arr):
		# TODO make this work?
		x, y = 0, 0
		self.pexpect_sessions[0].write_to_manager_logfile('==========DEBUG SCREEN ARRAY============')
		self.pexpect_sessions[0].write_to_manager_logfile('height: ' + str(screen_arr.height))
		self.pexpect_sessions[0].write_to_manager_logfile('width: ' + str(screen_arr.width))
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
			self.pexpect_sessions[0].write_to_manager_logfile('line: ' + str(y) + line)
			y += 1
		self.pexpect_sessions[0].write_to_manager_logfile('==========DEBUG SCREEN ARRAY END============')

	def scroll_back(self):
		# for each session: take the pointer, and move the _end_ pointer back to the output_top_visible_line_index - 1 and re-display
		return_msg = ''
		for session in self.pexpect_sessions:
			if session.session_pane:
				if session.output_lines_end_pane_pointer is not None and session.output_lines_end_pane_pointer > 0:
					session.output_lines_end_pane_pointer = session.output_top_visible_line_index-1
					session.output_top_visible_line_index = None
				else:
					return_msg = ' at least one session has hit the top'
		return return_msg

	def scroll_forward(self):
		# for each session: take the pointer, and move forward n lines, where n is the height of the pane. if greater than length, do nothing and re-display
		return_msg = ''
		for session in self.pexpect_sessions:
			if session.session_pane:
				if session.output_lines_end_pane_pointer is not None and session.output_lines_end_pane_pointer < len(session.output_lines):
					session.output_top_visible_line_index = session.output_lines_end_pane_pointer+1
					session.output_lines_end_pane_pointer = None
				else:
					return_msg = ' at least one session has hit the end'
		return return_msg

	def move_panes_to_tail(self):
		for session in self.pexpect_sessions:
			session.output_lines_end_pane_pointer = len(session.output_lines)-1

	def get_pane_by_session_number(self, session_number):
		for session in self.pexpect_sessions:
			if session.session_number == session_number:
				return session.session_pane
		return None


class PexpectSession(object):

	def __init__(self, command, pexpect_session_manager, session_number, pane_name=None, pane_color=red, encoding='utf-8', logtimestep=False):
		self.pexpect_session               = None
		self.session_number                = session_number
		self.command                       = command
		self.output_lines                  = []
		self.output_lines_end_pane_pointer = None
		# Pointer to the uppermost-visible PexpectSessionLine in this pane
		self.output_top_visible_line_index = None
		self.pid                           = None
		self.encoding                      = encoding
		self.pexpect_session_manager       = pexpect_session_manager
		self.logfilename                   = pexpect_session_manager.logdir + '/' + str(self.session_number) + '.autotrace.' + str(pexpect_session_manager.pid) + '.log'
		self.logfile                       = open(self.logfilename,'w+')
		self.logtimestep                   = logtimestep
		# Append to sessions
		self.pexpect_session_manager.pexpect_sessions.append(self)
		if self.session_number == 0:
			pexpect_session_manager.main_command_session = self
		self.session_pane                  = None
		if pane_name:
			self.session_pane              = SessionPane(pane_name, pane_color)
			self.session_pane.top_left     = (-1,-1)
			self.session_pane.bottom_right = (-1,-1)
		assert isinstance(self.session_number, int)


	def __str__(self):
		string =  '\n============= SESSION OBJECT BEGIN ==================='
		string += '\nsession_number: ' + str(self.session_number)
		string += '\ncommand: ' + str(self.command)
		string += '\npid: ' + str(self.pid)
		string += '\noutput_lines length: ' + str(len(self.output_lines))
		if self.output_lines_end_pane_pointer is not None:
			string += '\noutput_lines_end_pane_pointer: ' + str(self.output_lines_end_pane_pointer)
		if self.output_top_visible_line_index is not None:
			string += '\noutput_top_visible_line_index: ' + str(self.output_top_visible_line_index)
		for line in self.output_lines:
			string += '\nline: ' + str(line.line_str)
		if self.session_pane is not None:
			string += '\nsession_pane: ' + str(self.session_pane)
		string += '\n============= SESSION OBJECT END   ==================='
		return string

	def write_out_session_to_fit_pane(self):
		"""This function is responsible for taking the state of the session and writing it out to its pane.
		"""
		if self.session_pane:
			assert self.session_pane
			width = self.session_pane.get_width()
			height = self.session_pane.get_height()
			lines_in_pane_str_arr  = []
			last_time_seen         = None
			output_lines_cursor    = None
			pane_line_counter      = None
			# Means: We know where we end but not where we start (scroll back)
			if self.output_top_visible_line_index is None and self.output_lines_end_pane_pointer is not None:
				pass
			# Means: We know where we start but not where we end (scroll forward)
			if self.output_top_visible_line_index is not None and self.output_lines_end_pane_pointer is None:
				pass
			# Means: We don't know where are! This happens at the start.
			#assert not (self.output_top_visible_line_index is None and self.output_lines_end_pane_pointer is None)

			for line_obj in self.output_lines:
				# We have moved to the next object in the output_lines array
				if output_lines_cursor is None:
					output_lines_cursor = 0
				else:
					output_lines_cursor += 1
				# If we go past the output line pointer, then break - we don't want to see any later lines.
				if self.output_lines_end_pane_pointer is not None and output_lines_cursor > self.output_lines_end_pane_pointer:
					break
				if self.logtimestep:
					if last_time_seen is None or int(line_obj.time_seen) > last_time_seen:
						lines_in_pane_str_arr.append(['AutotraceTime:' + str(int(line_obj.time_seen)), output_lines_cursor])
					last_time_seen = int(line_obj.time_seen)
				# Strip whitespace at end, including \r\n
				line = line_obj.line_str.rstrip()
				if pane_line_counter is None and self.output_top_visible_line_index == output_lines_cursor:
					# We are within the realm of the pane now
					pane_line_counter = 0
				break_at_end_of_this_line = False
				while len(line) > width-1:
					# When we get to the top visible line index, kick off the
					# counter and up one for each pane line computed.
					lines_in_pane_str_arr.append([line[:width-1], output_lines_cursor])
					line = line[width-1:]
					if pane_line_counter is not None:
						pane_line_counter += 1
						if pane_line_counter > height - 1:
							# Make sure we finish this line, so iterate until done!
							break_at_end_of_this_line = True
				if break_at_end_of_this_line:
					break
				lines_in_pane_str_arr.append([line, output_lines_cursor])
				if pane_line_counter is not None:
					pane_line_counter += 1
					if pane_line_counter > height - 1:
						break
			output_lines_end_pane_pointer_has_been_set = False
			for i, line in zip(reversed(range(self.session_pane.top_left_y,self.session_pane.bottom_right_y)), reversed(lines_in_pane_str_arr)):
				self.pexpect_session_manager.screen_arr[i:i+1, self.session_pane.top_left_x:self.session_pane.top_left_x+len(line[0])] = [self.session_pane.color(line[0])]
				if not output_lines_end_pane_pointer_has_been_set:
					self.output_lines_end_pane_pointer = line[1]
					output_lines_end_pane_pointer_has_been_set = True
				# Record the uppermost-visible line
				self.output_top_visible_line_index = line[1]

	def spawn(self):
		self.pexpect_session = pexpect.spawn(self.command)
		self.pid             = self.pexpect_session.pid
		if self.session_number == 0:
			pexpect.run('kill -STOP ' + str(self.pid))

	def write_to_session_logfile(self, msg, line_type):
		assert isinstance(line_type,str)
		self.logfile.write(self.pexpect_session_manager.get_elapsed_time_str() + ' ' + line_type + ' ' + str(msg) + '\n')
		self.logfile.flush()

	def read_line(self):
		if not self.pexpect_session:
			return False
		string = None
		try:
			self.pexpect_session.expect('\r\n',timeout=self.pexpect_session_manager.timeout_delay)
			string = self.pexpect_session.before.decode(self.encoding) + '\r\n'
		except pexpect.EOF:
			self.pexpect_session_manager.write_to_manager_logfile('Command session: done ' + self.command)
			self.pexpect_session = None
		except pexpect.TIMEOUT:
			# This is ok. Not logged for perf reasons
			#self.pexpect_session_manager.write_to_manager_logfile('Timeout in command session: ' + self.command)
			pass
		except Exception as eg:
			self.pexpect_session_manager.write_to_manager_logfile('Error in command session: ' + self.command)
			self.pexpect_session_manager.write_to_manager_logfile(eg)
		if string:
			line_type = 'program_output'
			self.write_to_session_logfile(string.strip(),line_type=line_type)
			self.append_output_line(string, line_type)
			return True
		return False

	def append_output_line(self, string, line_type):
		# We should be 'un-paused' at this point, so in tailing mode.
		self.output_lines.append(PexpectSessionLine(string, self.pexpect_session_manager.get_elapsed_time(), line_type))
		if self.output_lines_end_pane_pointer is None:
			self.output_lines_end_pane_pointer = len(self.output_lines)-1
		else:
			self.output_lines_end_pane_pointer += 1
		# Move pane visibility along one too if the state is .
		if self.output_top_visible_line_index is not None:
			self.output_top_visible_line_index += 1


# Represents a line in the array of output
class PexpectSessionLine(object):
	def __init__(self, line_str, time_seen, line_type):
		self.line_str          = line_str
		self.time_seen         = time_seen
		self.line_type         = line_type
		# A 'display_sync_line' is an empty line designed to ensure that display syncs time-wise.
		assert self.line_type in ('program_output','display_sync_line')


# Represents a pane with no concept of context or content.
class SessionPane(object):

	def __init__(self, name, color):
		self.name                    = name
		self.top_left_x              = -1
		self.top_left_y              = -1
		self.bottom_right_x          = -1
		self.bottom_right_y          = -1
		self.color                   = color

	def __str__(self):
		string =  '\n============= SESSION PANE OBJECT BEGIN ==================='
		string += '\nname: '           + str(self.name)
		string += '\ntop_left_x: '     + str(self.top_left_x)
		string += '\ntop_left_y: '     + str(self.top_left_y)
		string += '\nbottom_right_x: ' + str(self.bottom_right_x)
		string += '\nbottom_right_y: ' + str(self.bottom_right_y)
		string += '\nwidth: '          + str(self.get_width())
		string += '\nheight: '          + str(self.get_width())
		string += '\n============= SESSION PANE OBJECT END   ==================='
		return string

	def set_position(self, top_left_x, top_left_y, bottom_right_x, bottom_right_y):
		self.top_left_x     = top_left_x
		self.top_left_y     = top_left_y
		self.bottom_right_x = bottom_right_x
		self.bottom_right_y = bottom_right_y

	def get_width(self):
		return self.bottom_right_x - self.top_left_x

	def get_height(self):
		return self.bottom_right_y - self.top_left_y


def process_args():
	parser = argparse.ArgumentParser(description='Analyse a process in real time.')
	parser.add_argument('commands', type=str, nargs='*', help='''Commands to autotrace, separated by spaces, eg: "autotrace 'find /' 'strace -p PID' 'vmstat 1'"''')
	parser.add_argument('-l', default=None, help='Folder to log output of commands to.')
	parser.add_argument('-v', action='store_const', const=True, default=None, help='Split vertically rather than horizontally (the default).')
	parser.add_argument('-d', action='store_const', const=True, default=None, help='Debug mode')
	parser.add_argument('--replayfile', help='Replay output of an individual file')
	parser.add_argument('--logtimestep',action='store_const', const=True, default=False,  help='Log each second tick in the output')
	args = parser.parse_args()
	# Validate BEGIN
	#if args.commands == [] and args.replayfile is None:
	#	print('You must supply either a command or a replayfile')
	#	parser.print_help(sys.stdout)
	#	sys.exit(1)
	if isinstance(args.commands,str):
		args.commands = [args.commands]
	if args.v and len(args.commands) > 2:
		print('-v and more than two commands supplied. -v does not make sense, so dropping that arg.')
		args.v = False
		time.sleep(1)
	if args.commands == [] and not args.replayfile:
		pid = get_last_run_pid()
		if pid:
			print(str(pid))
		else:
			print('No pid found')
			sys.exit(0)
	return args


def replace_pid(string, pid_str):
	assert isinstance(pid_str, str)
	return string.replace('PID', pid_str)

def get_last_run_pid(encoding='utf-8'):
	# GET CURRENT TTY: tty | sed 's/^.dev.\(.*\)/\1/'

	# Get all processes with a tty

	# Check stopped jobs first CTRL-Z
	jobs_command = 'jobs -p -s'
	ps_output  = pexpect.run(jobs_command).decode(encoding)
	print(ps_output)
	pids       = []
	for l in ps_output.split('\r\n'):
		pid = l.split(' ')[0].strip()
		if pid == '':
			continue
		print(pid)
		assert int(pid), 'pid is not an integer: ' + str(pid)
		pids.append(pid)
	if pids == []:
		# Then look for running jobs
		jobs_command = 'jobs -p -r'
		ps_output  = pexpect.run(jobs_command).decode(encoding)
		print(ps_output)
		pids       = []
		for l in ps_output.split('\r\n'):
			pid = l.split(' ')[0].strip()
			if pid == '':
				continue
			assert int(pid), 'pid is not an integer: ' + str(pid)
			pids.append(pid)
	if pids != []:
		# TODO: get the command (ps -ww -p PID), and re-run (as we can't attach it - emit warning at the end to kill off that process)
		# TODO: ask user whether they want to kill the process or 
		return pids[-1]
	else:
		return None

	# THEN LOOK FOR 'OTHER' JOBS BY THIS USER?
	#ps_command = 'ps -o pid=,comm='
	#ps_output  = pexpect.run(ps_command).decode(encoding)
	#pids       = []
	#for l in ps_output.split('\r\n'):
	#	# TODO If line contains ps_command, ignore
	#	if l.find(ps_command) != -1:
	#		continue
	#	print(l)
	#	pid = l.split(' ')[0].strip()
	#	if pid == '':
	#		continue
	#	assert int(pid), 'pid is not an integer: ' + str(pid)
	#	pids.append(pid)
	## TODO: not working on mac (wrong date binary)
	## TODO: use jobs to find background commands. foreground it if necessary
	## TODO: if no background command, 
	#date_command = 'date'
	#times = {}
	#for pid in pids:
	#	command = """bash -c '(export TZ=UTC0; export LC_ALL=C; date -d "$(ps -o start= -p '""" + pid + """')" +%s)'"""
	#	print(command)
	#	process_time_s = pexpect.run(command).decode(encoding).strip()
	#	if process_time_s[:5] == 'usage':
	#		# TODO: handle mac
	#		print('asd')
	#	assert int(process_time_s)
	#	times.update({process_time_s:pid})
	#	# TODO: order by time, remove first one (the shell), pick the last one


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
					pexpect_session_manager.draw_screen('sessions',quick_help=pexpect_session_manager.get_quick_help())
					pexpect_session_manager.handle_sessions()
					pexpect_session_manager.handle_input()
			except KeyboardInterrupt:
				pexpect_session_manager.refresh_window()


autotrace_version='0.0.8'
if __name__ == '__main__':
	main()
