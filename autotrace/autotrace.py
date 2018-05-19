from __future__ import unicode_literals
from __future__ import print_function
import argparse
import platform
import os
import sys
import time
import re
import pexpect
import curtsies
from curtsies.fmtfuncs import black, yellow, magenta, cyan, gray, blue, red, green, on_black, on_dark, on_red, on_green, on_yellow, on_blue, on_magenta, on_cyan, on_gray, bold, dark, underline, blink, invert, plain
from curtsies.events import PasteEvent
from curtsies.input import Input

# Example code for debug/breakpoint
#if self.pexpect_session_manager.trigger_debug and self.session_number == 1:
#   print("\nrestore terminal? import os; os.system('stty sane')\n")
#	import code; code.interact(local=dict(globals(), **locals()))
#	import pdb; pdb.set_trace()

PY3 = sys.version_info[0] >= 3
if PY3:
	unicode = str

# TODO: BUG - down doesn't work at end of first screen
# TODO: tar up logfiles as a bug report

class PexpectSessionManager(object):
	# Singleton
	only_one = None
	def __init__(self, logdir=None, debug=False, encoding='utf-8'):
		"""

		only_one             -
		debug                -
		"""
		assert self.only_one is None
		self.only_one             = True
		self.root_ready           = False
		if os.getuid() == 0:
			self.root_ready = True
		self.debug                = debug
		self.pexpect_sessions     = []
		self.status               = 'Running'
		self.status_message       = ''
		self.main_command_session = None
		self.pid                  = os.getpid()
		self.timeout_delay        = 0.001
		self.encoding             = encoding
		self.zoomed_session       = None
		self.trigger_debug        = False
		self.pointers_fixed       = False
		if logdir is not None:
			assert isinstance(logdir, str)
			self.logdir               = logdir
			os.system('mkdir -p ' + self.logdir)
		else:
			self.logdir               = '/tmp/tmp_autotrace/' + str(self.pid)
			os.system('mkdir -p ' + self.logdir)
			if self.root_ready:
				os.system('chmod -R 777 /tmp/tmp_autotrace')
		self.logfilename          = self.logdir + '/manager.autotrace.' + str(self.pid) + '.log'
		self.logfile              = open(self.logfilename,'w+')
		os.chmod(self.logfilename,0o777)
		# Does user have root?
		# TODO: emit warning if not root?
		self.root_ready     = False
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
			self.write_to_manager_logfile('DEBUG MESSAGE: ' + msg)
		if pause:
			time.sleep(pause)

	def refresh_window(self):
		self.window               = curtsies.FullscreenWindow(hide_cursor=True)
		self.screen_arr           = None
		self.wheight              = self.window.height
		self.wwidth               = self.window.width
		# Divide the screen up into two, to keep it simple for now
		self.wheight_top_end	  = int(self.wheight / 2)
		self.wheight_bottom_start = int(self.wheight / 2)
		self.wwidth_left_end	  = int(self.wwidth / 2)
		self.wwidth_right_start   = int(self.wwidth / 2)
		assert self.wheight >= 24, self.quit_autotrace('Terminal not tall enough!')
		assert self.wwidth >= 80, self.quit_autotrace('Terminal not wide enough!')


	def clear_screen_arr(self):
		for y in range(0,self.wheight):
			line = ' '*self.wwidth
			self.screen_arr[y:y+1,0:len(line)] = [line]

	def write_to_manager_logfile(self, msg):
		if isinstance(msg, PasteEvent):
			msg = str(msg)
		assert isinstance(msg, unicode), str(type(msg))
		self.logfile.write(self.get_elapsed_time_str() + ' ' + str(msg) + '\n')
		self.logfile.flush()

	def cycle_panes(self):
		# Must have more than 4 panes to do a cycle (including main command)
		if len(self.pexpect_sessions) <= 4:
			return
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
		assert draw_type in ('sessions','help','clearscreen')
		self.screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		# Header
		if self.status_message:
			header_text = 'Autotrace state: ' + invert(self.status) + ', ' + self.status_message
		else:
			header_text = 'Autotrace state: ' + invert(self.status)
		self.screen_arr[0:1,0:len(header_text)] = [blue(header_text)]
		# Footer
		space = (self.wwidth - len(quick_help))*' '
		footer_text = space + quick_help
		self.screen_arr[self.wheight-1:self.wheight,0:len(footer_text)] = [invert(blue(footer_text))]
		# Draw the sessions.
		if draw_type == 'sessions':
			# Is there a zoomed session? Just write that one out.
			if self.zoomed_session:
				self.do_layout('zoomed')
				self.zoomed_session.write_out_session_to_fit_pane()
			else:
				for session in self.pexpect_sessions:
					session.write_out_session_to_fit_pane()
		elif draw_type == 'help':
			self.draw_help()
		elif draw_type == 'clearscreen':
			self.clear_screen_arr()
		if not self.debug:
			self.window.render_to_terminal(self.screen_arr, cursor_pos=(self.wheight, self.wwidth))

	def draw_help(self):
		help_text_lines = self.get_state_for_user().split('\n')
		i=2
		for line in help_text_lines:
			while len(line) > self.wwidth-1:
				line = line[:self.wwidth-1]
				self.screen_arr[i:i+1,0:len(line)] = [green(line)]
				line = line[self.wwidth:]
				i += 1
			self.screen_arr[i:i+1,0:len(line)] = [green(line)]
			i += 1

	def quit_autotrace(self, msg='All done.'):
		self.screen_arr = curtsies.FSArray(self.wheight, self.wwidth)
		self.window.render_to_terminal(self.screen_arr)
		print(msg + self.get_state_for_user())
		os.system('stty echo')
		sys.exit(0)

	def get_state_for_user(self):
		msg = '\nLogs and output in: ' + self.logdir
		msg += '\nCommands were: '
		for session in self.pexpect_sessions:
			msg += '\n\t' + session.command
		return msg

	def handle_sessions(self):
		seen_output = False
		all_done    = False
		lines_seen = {}
		while not seen_output:
			a_session_is_still_active = False
			for session in self.pexpect_sessions:
				lines_seen.update({session:False})
				if session.read_line():
					seen_output = True
					lines_seen.update({session:True})
				if session.pexpect_session is not None:
					a_session_is_still_active = True
					#self.debug_msg('session: ' + str(session) + ' is still active')
			if not a_session_is_still_active:
				self.debug_msg('All sessions complete, breaking out')
				all_done = True
				break
		# Determine which ones saw output.
		# The ones that did not need to 'fake read' a line of type 'display_sync_line'
		assert seen_output or all_done
		if seen_output:
			for session in self.pexpect_sessions:
				if not lines_seen[session]:
					session.append_output_line('','display_sync_line')

	def get_quick_help(self):
		if self.status == 'Running':
			number_of_sessions = len(self.pexpect_sessions)
			zoom_str = ''
			for i in range(0,number_of_sessions):
				if self.get_pane_by_session_number(i) is not None:
					if i > 0:
						zoom_str += ',' + str(i)
					else:
						zoom_str += str(i)
			if number_of_sessions > 4:
				if self.zoomed_session:
					quick_help = 'q/ESC/C-d: quit, p: pause, c: continue, r: refresh, z: zoom out, h: help =>  '
				else:
					quick_help = 'q/ESC/C-d: quit, p: pause, c: continue, r: refresh, m: cycle windows, ' + zoom_str + ': zoom, h: help =>  '
			else:
				quick_help = 'q/ESC/C-d: quit, p: pause, r: refresh, h: help =>  '
		elif self.status == 'Paused':
			quick_help = 'q/ESC/C-d: quit, c: continue, j/k: scroll down/up: f/b: page forward/back, r: refresh, h: help =>  '
		elif self.status == 'Help':
			quick_help = 'q/ESC/C-d: quit, c: continue, r: refresh =>  '
		return quick_help



	def handle_input(self):
		self.trigger_debug = False
		quit_chars = (u'<ESC>', u'<Ctrl-d>', u'q')
		with Input() as input_generator:
			input_char = input_generator.send(self.timeout_delay)
			if isinstance(input_char, PasteEvent):
				input_char = str(input_char)[-1]
			if input_char:
				self.write_to_manager_logfile('input_char: ' + input_char)
			if input_char in quit_chars:
				self.quit_autotrace(msg=input_char + ' hit, quitting.')
			elif input_char in (u'r',):
				self.draw_screen('clearscreen',quick_help=self.get_quick_help())
			elif input_char in (u'd',):
				self.trigger_debug = True
			elif input_char in (u'm',):
				self.cycle_panes()
				self.draw_screen('sessions',quick_help=self.get_quick_help())
			elif input_char in (u'z',):
				# Revert layout status from zoomed
				self.zoomed_session = None
				self.do_layout('default')
				self.draw_screen('sessions',quick_help=self.get_quick_help())
			elif input_char in [str(x) for x in range(0,len(self.pexpect_sessions))]:
				if self.zoomed_session is None:
					# Only accept if pane is assigned to this session.
					if self.get_pane_by_session_number(int(input_char)) is not None:
						# Set session as zoomed.
						for session in self.pexpect_sessions:
							if session.session_number == int(input_char):
								self.zoomed_session = session
						assert self.zoomed_session
						# Redraw screen
						self.draw_screen('sessions',quick_help=self.get_quick_help())
				else:
					self.zoomed_session = None
					self.do_layout('default')
					self.draw_screen('sessions',quick_help=self.get_quick_help())
			elif input_char in (u'p',):
				# Handle paused state
				self.status = 'Paused'
				self.pause_sessions()
				self.draw_screen('sessions',quick_help=self.get_quick_help())
				for e in input_generator:
					if e:
						self.write_to_manager_logfile('input_char: ' + e)
					if e in quit_chars:
						self.quit_autotrace()
					elif e in (u'd',):
						self.trigger_debug = True
					elif e in (u'r',):
						self.draw_screen('clearscreen',quick_help=self.get_quick_help())
						self.status_message = 'you just refreshed '
						self.draw_screen('sessions',quick_help=self.get_quick_help())
					elif e == 'c':
						self.move_panes_to_tail()
						self.unpause_sessions()
						self.status = 'Running'
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						self.pointers_fixed = False
						break
					elif e == 'j':
						msg = self.scroll_down_one()
						self.status_message = 'you just scrolled down one ' + msg
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						self.pointers_fixed = False
					elif e == 'k':
						msg = self.scroll_up_one()
						self.status_message = 'you just scrolled up one ' + msg
						self.pointers_fixed = True
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						self.pointers_fixed = False
					elif e == 'b':
						msg = self.page_backward()
						self.status_message = 'you just hit back ' + msg
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						self.pointers_fixed = False
					elif e in ('f','<SPACE>'):
						msg = self.page_forward()
						self.status_message = 'you just hit forward ' + msg
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						self.pointers_fixed = False
					else:
						self.write_to_manager_logfile('input_char unhandled in paused: ' + input_char)
			elif input_char in (u'h',):
				# Handle help state
				self.status = 'Help'
				# Default is to pause sessions here - good idea?
				self.pause_sessions()
				self.draw_screen('help',quick_help=self.get_quick_help())
				for e in input_generator:
					if e:
						self.write_to_manager_logfile('input_char: ' + e)
					if e in quit_chars:
						# TODO: maybe go back to running from here?
						self.quit_autotrace()
					elif e in (u'd',):
						self.trigger_debug = True
					elif e in (u'r',):
						self.draw_screen('clearscreen',quick_help=self.get_quick_help())
						self.status_message = 'you just refreshed ' + msg
						self.draw_screen('sessions',quick_help=self.get_quick_help())
					elif e == 'c':
						self.unpause_sessions()
						self.status = 'Running'
						self.draw_screen('sessions',quick_help=self.get_quick_help())
						break
					else:
						self.write_to_manager_logfile('input_char unhandled in help: ' + input_char)
				else:
					self.write_to_manager_logfile('input_char unhandled in wider loop: ' + input_char)

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
				#session_1_command = 'dtruss -f -p ' + str(main_session.pid)
				session_1_command = 'iostat 1'
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


	def do_layout(self,layout):
		assert isinstance(layout, unicode), 'layout is of type: ' + str(type(layout))
		if layout == 'default':
			self.do_layout_default()
		elif layout == 'zoomed':
			self.do_layout_zoomed()
		else:
			assert False, 'do_layout: ' + layout + ' not handled'

	def do_layout_zoomed(self):
		# TODO: maybe do this 'properly' and set the pane's positions and visibility fully, and revert to previous when done.
		assert self.zoomed_session
		zoomed_session = None
		for session in self.pexpect_sessions:
			if session == self.zoomed_session:
				zoomed_session = session
				break
		assert zoomed_session
		assert zoomed_session.session_pane
		zoomed_session.session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)

	def do_layout_default(self):
		main_session_pane      = None
		bottom_left_pane       = None
		bottom_right_pane      = None
		top_right_pane         = None
		for session in self.pexpect_sessions:
			if session.session_number == 0:
				main_session_pane = session.session_pane
			elif session.session_pane and session.session_pane.name == 'bottom_left':
				bottom_left_pane    = session.session_pane
			elif session.session_pane and session.session_pane.name == 'bottom_right':
				bottom_right_pane    = session.session_pane
			elif session.session_pane and session.session_pane.name == 'top_right':
				top_right_pane    = session.session_pane
		assert main_session_pane is not None and bottom_left_pane is not None

		if top_right_pane is None:
			# Two panes only, so are we vertically split?
			if self.vertically_split:
				main_session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight-1)
			else:
				main_session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight_bottom_start)
		else:
			# At least 3 sessions (4 including main), so set up main session in top left...
			main_session_pane.set_position(top_left_x=0, top_left_y=1, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight_bottom_start)
			# ... and then session 3 setup in top right.
			top_right_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=1, bottom_right_x=self.wwidth, bottom_right_y=self.wheight_bottom_start)
		if bottom_right_pane is None:
			# Two panes only, so are we vertically split?
			if self.vertically_split:
				bottom_left_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=0, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)
			else:
				bottom_left_pane.set_position(top_left_x=0, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)
		else:
			# At least 2 sessions (3 including main), so set up second session in bottom left...
			bottom_left_pane.set_position(top_left_x=0, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth_left_end, bottom_right_y=self.wheight-1)
			# ... and then session 3 in bottom right.
			bottom_right_pane.set_position(top_left_x=self.wwidth_right_start, top_left_y=self.wheight_bottom_start, bottom_right_x=self.wwidth, bottom_right_y=self.wheight-1)


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

	def scroll_down_one(self):
		return_msg = ''
		for session in self.pexpect_sessions:
			if session.session_pane:
				if session.output_lines_end_pane_pointer is not None and session.output_lines_end_pane_pointer > 0:
					session.output_lines_end_pane_pointer += 1
					if session.output_top_visible_line_index is not None and session.output_top_visible_line_index > 0:
						session.output_top_visible_line_index += 1
				else:
					return_msg = ' at least one session has hit the top'
		return return_msg

	def scroll_up_one(self):
		return_msg = ''
		for session in self.pexpect_sessions:
			if session.session_pane:
				if session.output_lines_end_pane_pointer is not None and session.output_lines_end_pane_pointer > 0:
					session.output_lines_end_pane_pointer -= 1
					if session.output_top_visible_line_index is not None and session.output_top_visible_line_index > 0:
						session.output_top_visible_line_index -= 1
				else:
					return_msg = ' at least one session has hit the top'
		return return_msg

	def page_backward(self):
		# for each session: take the pointer, and move the _end_ pointer back to the output_top_visible_line_index - 1 and re-display
		return_msg = ''
		for session in self.pexpect_sessions:
			if session.session_pane:
				if session.output_lines_end_pane_pointer is not None and session.output_lines_end_pane_pointer > 0:
					if session.output_top_visible_line_index is not None and session.output_top_visible_line_index > 0:
						session.output_lines_end_pane_pointer = session.output_top_visible_line_index-1
					session.output_top_visible_line_index = None
				else:
					return_msg = ' at least one session has hit the top'
		return return_msg

	def page_forward(self):
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
		assert isinstance(session_number,int)
		for session in self.pexpect_sessions:
			if session.session_number == session_number:
				return session.session_pane
		return None


class PexpectSession(object):

	def __init__(self, command, pexpect_session_manager, session_number, pane_name=None, pane_color=red, encoding='utf-8', logtimestep=False):
		"""

		pexpect_session               - The pexpect object that is held within
		                                this session.
		session_number                - Index of session - 0 is reserved for the
		                                'main' command. This does not change,
		                                unlike the session_pane value which
		                                changes depending on which SessionPane
		                                the session is assigned to in the window.
		command                       - The command tracked in this session
		output_lines                  - The lines of output. Each line is a
		                                PexpectSessionLine object.
		output_lines_end_pane_pointer - Used for scrolling, this tracks which
		                                output_lines index is at the end of the
		                                pane as displayed.
		output_top_visible_line_index - Used for scrolling, this tracks which
		                                output_lines index is at the top of the
										pane as displayed.
		pid                           - The process ID that this session
		                                spawned.
		encoding                      - Text encoding for this session's output.
		pexpect_session_manager       - Reference to global window/controlling
		                                object.
		logfilename                   - Name of logfile for this session.
		logfile                       - Python file object for logfile.
		logtimestep                   - Whether to log each second in the output.
		session_pane                  - SessionPane object that this session is
		                                assigned to. If None, session is not
		                                being displayed.
		"""
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
		self.session_pane                  = None
		# Append to sessions
		self.pexpect_session_manager.pexpect_sessions.append(self)
		if self.session_number == 0:
			pexpect_session_manager.main_command_session = self
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
		string += '\noutput_lines_end_pane_pointer: ' + str(self.output_lines_end_pane_pointer)
		string += '\noutput_top_visible_line_index: ' + str(self.output_top_visible_line_index)
		#for line in self.output_lines:
		#	string += '\nline: ' + str(line.line_str)
		string += '\nsession_pane: ' + str(self.session_pane)
		string += '\n============= SESSION OBJECT END   ==================='
		return string

	def write_out_session_to_fit_pane(self):
		"""This function is responsible for taking the state of the session and writing it out to its pane.
		"""
		if self.session_pane:
			assert self.session_pane
			pane_width  = self.session_pane.get_width()
			pane_height = self.session_pane.get_height()
			# We reserve one row at the end as a pane status line
			available_pane_height   = self.session_pane.get_height() - 1
			lines_in_pane_str_arr   = []
			last_time_seen          = None
			output_lines_cursor     = None
			pane_line_counter       = None
			end_known_but_not_start = None
			start_known_but_not_end = None
			start_and_end_known     = None
			if len(self.output_lines) != 0:
				if self.output_top_visible_line_index is None and self.output_lines_end_pane_pointer is not None:
					self.pexpect_session_manager.write_to_manager_logfile('We know where we end but not where we start: end at: ' + str(self.output_lines_end_pane_pointer))
					end_known_but_not_start = True
				elif self.output_top_visible_line_index is not None and self.output_lines_end_pane_pointer is None:
					self.pexpect_session_manager.write_to_manager_logfile('We know where we start but not where we end: start at: ' + str(self.output_top_visible_line_index))
					start_known_but_not_end = True
				elif self.output_top_visible_line_index is not None and self.output_lines_end_pane_pointer is not None:
					start_and_end_known = True
				assert start_known_but_not_end or end_known_but_not_start or start_and_end_known, str(self)
			else:
				# Neither is set. This is OK at the start, ie len of output_lines is zero.
				assert self.output_top_visible_line_index is None and self.output_lines_end_pane_pointer is None
			for line_obj in self.output_lines:
				# We have moved to the next object in the output_lines array
				if output_lines_cursor is None:
					output_lines_cursor = 0
				else:
					output_lines_cursor += 1
				if pane_line_counter is None and self.output_top_visible_line_index == output_lines_cursor:
					# We are within the realm of the pane now. plc starts at 1.
					pane_line_counter = 1
				# If we go past the output line pointer, then break - we don't want to see any later lines.
				if self.output_lines_end_pane_pointer is not None and output_lines_cursor > self.output_lines_end_pane_pointer:
					break
				if self.logtimestep:
					if last_time_seen is None or int(line_obj.time_seen) > last_time_seen:
						lines_in_pane_str_arr.append(['AutotraceTime:' + str(int(line_obj.time_seen)), output_lines_cursor])
					last_time_seen = int(line_obj.time_seen)
				# Strip whitespace at end, including \r\n
				line = line_obj.line_str.rstrip()
				break_at_end_of_this_line = False
				# If line is so long that it's going to take over the end of the pane, then bail.
				# If the pane_line_counter + the number of lines that this line will take up
				#num_pane_lines_taken_up = (len(line)/pange_width-1)+1
				# The following code, while neat, causes a bug where screens do not 'move on'.
				# BROKEN CODE BEGINS
				#if pane_line_counter is not None and pane_line_counter+num_pane_lines_taken_up > available_pane_height:
				#	break
				#else:
				while len(line) > pane_width-1:
					# When we get to the top visible line index, kick off the
					# counter and up one for each pane line computed.
					lines_in_pane_str_arr.append([line[:pane_width-1], output_lines_cursor])
					line = line[pane_width-1:]
					if pane_line_counter is not None:
						pane_line_counter += 1
						if pane_line_counter > available_pane_height:
							# Make sure we finish this line, so iterate until done!
							break_at_end_of_this_line = True
				# BROKEN CODE ENDS
				if break_at_end_of_this_line:
					break
				else:
					# Add the remainder of this line.
					lines_in_pane_str_arr.append([line, output_lines_cursor])
					if pane_line_counter is not None:
						pane_line_counter += 1
						if pane_line_counter > available_pane_height:
							break
			# Add a status line in the pane
			line_str = 'Session no: ' + str(self.session_number) + ', command: ' + self.command
			line_str = line_str[:pane_width]
			took_up_whole_pane = False
			if lines_in_pane_str_arr:
				lines_in_pane_str_arr.append([line_str, output_lines_cursor+1])
				if pane_line_counter is not None and pane_line_counter > available_pane_height:
					took_up_whole_pane = True
			else:
				# Nothing to display - just display the status line.
				if output_lines_cursor is None:
					output_lines_cursor = 0
				lines_in_pane_str_arr.append([line_str, output_lines_cursor])
			top_y                                      = self.session_pane.top_left_y
			bottom_y                                   = self.session_pane.bottom_right_y
			output_lines_end_pane_pointer_has_been_set = False
			for i, line_obj in zip(reversed(range(top_y,bottom_y)), reversed(lines_in_pane_str_arr)):
				# Status on bottom line
				# If    this is on the top, and height + top_y value == i (ie this is the last line of the pane)
				#    OR this is on the bottom (ie top_y is not 1), and height + top_y == i
				if (top_y == 1 and available_pane_height + top_y == i) or (top_y != 1 and available_pane_height + top_y == i):
					self.pexpect_session_manager.screen_arr[i:i+1, self.session_pane.top_left_x:self.session_pane.top_left_x+len(line_obj[0])] = [cyan(invert(line_obj[0]))]
				else:
					self.pexpect_session_manager.screen_arr[i:i+1, self.session_pane.top_left_x:self.session_pane.top_left_x+len(line_obj[0])] = [self.session_pane.color(line_obj[0])]
				if not output_lines_end_pane_pointer_has_been_set and self.pexpect_session_manager.pointers_fixed is False:
					self.output_lines_end_pane_pointer = line_obj[1]
					output_lines_end_pane_pointer_has_been_set = True
				if self.pexpect_session_manager.pointers_fixed is False:
					# Record the uppermost-visible line
					self.output_top_visible_line_index = line_obj[1]


	def spawn(self):
		self.pexpect_session = pexpect.spawn(self.command)
		self.pid             = self.pexpect_session.pid
		if self.session_number == 0:
			pexpect.run('kill -STOP ' + str(self.pid))

	def write_to_session_logfile(self, msg, line_type):
		assert isinstance(line_type,str) or isinstance(line_type,unicode) # python is lazy
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
		# Move pane visibility along one too if the state is not None.
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
		assert self.name in ('top_left','bottom_left','top_right','bottom_right')

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
	parser.add_argument('--replay', nargs='?', help='Replay output of a folder. Optionally, you can give the pid of the process that is in the filenames if there are more than one set of logfiles in the folder.')
	parser.add_argument('--replayfile', nargs=1, help='Replay output of an individual file')
	parser.add_argument('--logtimestep',action='store_const', const=True, default=False,  help='Log each second tick in the output')
	args = parser.parse_args()
	# Validate BEGIN
	if isinstance(args.commands,str):
		args.commands = [args.commands]
	if args.v and len(args.commands) > 2:
		print('-v and more than two commands supplied. -v does not make sense, so dropping that arg.')
		args.v = False
		time.sleep(1)
	if args.commands == [] and not args.replayfile and not args.replay:
		pid, command = get_last_run_pid()
		if pid is None and command is None:
			# TODO: find a process: ps -u imiell -a
			#
			#       ps -u imiell -a -o pid=,tt= | grep -vw '?$'
			#       If linux, just look for processes with pts ttys
			print('No background process found on this terminal session.')
			sys.exit(1)
		if command:
			args.commands.append(command)
		elif pid is not None:
			args.commands.append("""echo bg command being tracked is: """ + command)
		args.commands.append('iostat 1')
		if pid is not None and platform.system() != 'Darwin':
			args.commands.append("""bash -c 'while true; do cat /proc/""" + str(pid) + """/status; sleep 2; done""")
		elif pid is None and platform.system() != 'Darwin':
			args.commands.append("""bash -c 'while true; do cat /proc/PID/status; sleep 2; done""")
		args.commands.append('vmstat 1')
	# Validate END
	# BUG! if logtimestep is false it's broked - is it?
	#args.logtimestep = True
	return args

def get_last_run_pid(encoding='utf-8'):
	# GET CURRENT TTY
	mytty = pexpect.run('ps -o tt= -p ' + str(os.getpid())).decode(encoding).strip()
	# ps -o etime | sort -r gets them in order.
	# The grep gets all processes with the same tty
	pses = pexpect.run("""bash -c '(export LC_ALL=C; ps -a -o etime=,tt=,pid=,args= | sort -r)'""").decode(encoding).strip()
	pses = pses.split('\r\n')
	pses_on_this_tty = []
	for line in pses:
		line_list = re.split(r'\s+', line.strip())
		if line_list[1] == mytty:
			pses_on_this_tty.append(line_list)
	if len(pses_on_this_tty) == 2:
		# Drop last one, as it's this python process.
		pses_on_this_tty = [pses_on_this_tty[0]]
	else:
		# Drop the first and last one, as they're the shell and this python process respectively.
		pses_on_this_tty = pses_on_this_tty[1:-1]
	# Take the last one in this list, as that's the last-started background process
	if len(pses_on_this_tty):
		pid = pses_on_this_tty[-1][2]
		command = ' '.join(pses_on_this_tty[-1][3:])
		pexpect.run('kill -STOP ' + pid)
		clear_screen()
		print('''

OOK, you are about to attach to the origin command:

	''' + command + '''

which has been suspended until you choose to continue or quit.

Output of the original command is not easily redirected away from this terminal.
However, you can replay the autotrace once the process is finished with:

	autotrace --replay <LOGDIR>

You have some choices:

- Enter           - restart the command and trace
- q and Enter     - restart the original command and quit
- z and Enter     - change nothing, just quit
- r and Enter     - kill off the already-started process and re-run with autotrace

=> ''')
		if PY3:
			resp = input()
		else:
			resp = raw_input()
		# Redirect output? Can't without other deps, but can replay
		if resp in ('z','Z'):
			sys.exit(0)
		if resp in ('r','R'):
			pexpect.run('kill -KILL ' + pid)
			return None, command
		elif resp in ('q','Q','',''):
			pexpect.run('kill -CONT ' + pid)
		if resp in ('q','Q'):
			sys.exit(0)
		return int(pid), command
	return None, None


def replace_pid(string, pid_str):
	assert isinstance(pid_str, str)
	return string.replace('PID', pid_str)


def clear_screen():
	# Completely clear screen (useful for debugging)
	# https://stackoverflow.com/questions/2084508/clear-terminal-in-python
	sys.stderr.write("\x1b[2J\x1b[H")
	# https://stackoverflow.com/questions/4842424/list-of-ansi-color-escape-sequences
	sys.stderr.write("\x1b[0")


def replay_file(pexpect_session_manager, filename):
	assert isinstance(filename,str)
	try:
		file_content = open(filename,'r').read()
	except FileNotFoundError:
		pexpect_session_manager.quit_autotrace('Replay file: "' + filename + '" not found')
	last_time_seen = 0.0
	for line in file_content.split('\n'):
		line = line.strip()
		if len(line) == 0:
			continue
		line_list = line.split(' ')
		assert len(line_list) > 0
		elapsed_time = float(line_list[0])
		time_to_wait = elapsed_time - last_time_seen
		last_time_seen = elapsed_time
		time.sleep(time_to_wait)
		line_type = line_list[1]
		if line_type == 'program_output':
			if len(line_list) > 2:
				line_str = ' '.join(line_list[2:])
				print(line_str)

def replay_dir(pexpect_session_manager, args):
	# For each file in the directory that matches the spec, spin up a session that runs:
	# autotrace --replayfile <FILENAME>
	if isinstance(args.replay, str):
		spec = [args.replay]
	else:
		spec = args.replay
	replaydir = None
	replaypid = None
	if len(spec) == 1:
		replaydir = spec[0]
		replaypid = '.*'
	elif len(spec) == 2:
		replaypid = spec[1]
	else:
		pexpect_session_manager.quit_autotrace('Wrong number of arguments passed to --replay: ' + str(len(spec)) + '\nShould be at most two.')
	assert replaydir is not None
	assert isinstance(replaydir,str)
	if not os.path.isdir(replaydir):
		pexpect_session_manager.quit_autotrace('Replay directory: "' + replaydir + '" is not a folder')
	# Collect the files in folder that match: <n>.autotrace.<pid>.log
	# For each session, create a session with command: '<<THIS BINARY/python invocation>> --replayfile <<FILENAME>>
	logfilenames = os.listdir(replaydir)
	logfilenames_dict = {}
	for logfilename in logfilenames:
		if re.match('[0-9]+.autotrace.[0-9]+.log',logfilename):
			num = int(logfilename.split('.')[0])
			logfilenames_dict.update({num:logfilename})
	# Order them by number.
	# 0 is the main session, 1,2, etc
	for c in range(0,len(logfilenames_dict)):
		logfilename = logfilenames_dict[c]
		session_command = sys.executable + ' ' + sys.argv[0] + ' --replayfile ' + replaydir + '/' + logfilename
		args.commands.append(session_command)


def main():
	args = process_args()
	pexpect_session_manager=PexpectSessionManager(args.l, debug=args.d)
	if args.replayfile:
		replay_file(pexpect_session_manager, args.replayfile[0])
	else:
		if args.replay:
			replay_dir(pexpect_session_manager, args)
		if args.commands:
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
				# TODO: doesn't reset if set back on
				#os.system('stty -echo')
				try:
					while True:
						pexpect_session_manager.draw_screen('sessions',quick_help=pexpect_session_manager.get_quick_help())
						pexpect_session_manager.handle_sessions()
						pexpect_session_manager.handle_input()
				except KeyboardInterrupt:
					pexpect_session_manager.draw_screen('clearscreen',quick_help=pexpect_session_manager.get_quick_help())
					pexpect_session_manager.refresh_window()
					pexpect_session_manager.quit_autotrace('Interrupt detected.')

################################################################################
# Basic flow of application
################################################################################
# draw_screen
# 	do_layout
# 		do_layout_default (or _zoomed)
# 	for each session that is displayed:
# 		write_out_session_to_fit_pane
# handle_sessions
#	reads lines from pexpect sessions
# handle_input
# 	(can also) draw_screen
################################################################################

autotrace_version='0.0.8'
if __name__ == '__main__':
	main()
