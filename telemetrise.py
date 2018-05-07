from __future__ import unicode_literals
import pexpect
import curtsies
import time
import sys
from curtsies.fmtfuncs import blue, red, green
from curtsies.formatstring import linesplit


def main(command):
	# TODO: put in global object
	command_session = pexpect.spawn(command)
	command_pid = command_session.pid
	pexpect.run('kill -STOP ' + str(command_pid))
	# Assumes strace exists... need to correct/handle cases where not, eg mac
	# or not installed. Also, what about root? TODO
	strace_session = pexpect.spawn('strace -f -p ' + str(command_pid))
	pexpect.run('kill -CONT ' + str(command_pid))

	command_output = ''
	strace_output = ''
	with curtsies.FullscreenWindow() as window:
		while True:
			# Setup
			wheight = window.height
			wwidth  = window.width
			a = curtsies.FSArray(wheight,wwidth)

			# Divide the screen up into two, to keep it simple for now
			wheight_top_end    = int(wheight / 2)
			wheight_bottom_start = int(wheight / 2) + 1
			wwidth_left_end = int(wwidth / 2)
			wwidth_right_start = int(wwidth / 2) + 1

			# Header
			header_text = 'telemetrise running on command: ' + command + ' ' + str(wheight) + 'x' + str(wwidth)
			a[0:1,0:len(header_text)] = [blue(header_text)]

			# Top half for command output
			# Split the lines by newline, then reversed and zip up with line 2 to halfway.
			if command_output != '':
				# TODO: write wrap function to wrap lines that are too long before splitting
				lines = command_output.split('\r\n')
				for i, line in zip(reversed(range(2,wheight_top_end)), reversed(lines)):
					a[i:i+1, 0:len(line)] = [green(line)]

			# Bottom left for strace output
			if strace_output != '':
				# TODO: write wrap function to wrap lines that are too long before splitting
				lines = strace_output.split('\r\n')
				for i, line in zip(reversed(range(wheight_bottom_start,wheight-2)), reversed(lines)):
					line = line[:50]
					a[i:i+1, 0:len(line)] = [red(line)]

			# Footer
			footer_text = 'telemetrise running on command: ' + command + ' ' + str(wheight) + 'x' + str(wwidth)
			a[wheight-1:wheight,0:len(footer_text)] = [blue(footer_text)]

			# We're done, now render!
			#write_to_logfile(a)
			window.render_to_terminal(a)

			# Now read input from main spawn
			char = None
			# 'while' keeps it line-oriented for reasonable performance...
			while char != '\n':
				if command_session:
					try:
						char=command_session.read_nonblocking(timeout=1)
					except pexpect.EOF:
						command_output += '\nDONE'
						command_session = None
					except:
						command_output += '?'
					if char:
						command_output += char.decode('utf-8')
				if strace_session:
					try:
						char=strace_session.read_nonblocking(timeout=1)
					except pexpect.EOF:
						strace_output += '\nDONE'
						strace_session = None
					except:
						strace_output += '?'
					if char:
						strace_output += char.decode('utf-8')


# TODO: object for each session
command = 'ping -c100 google.com'
logfile = open('outfile','w')


def write_to_logfile(msg):
	global logfile
	logfile.write(str(msg) + '\n')
	logfile.flush()


if __name__ == '__main__':
	main(command)
