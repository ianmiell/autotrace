from __future__ import unicode_literals
import pexpect
import curtsies
import time
import sys
from curtsies.fmtfuncs import blue, red, green
from curtsies.formatstring import linesplit

def main(command):
	pexpect_session = pexpect.spawn(command)
	command_pid = pexpect_session.pid
	pexpect.run('kill -STOP $PID')
	# Assumes strace exists... need to correct/handle cases where not, eg mac
	# or not installed. Also, what about root? TODO
	strace_session = pexpect.spawn('strace -f -p $PID')
	pexpect.run('kill -CONT $PID')

	command_output = ''
	with curtsies.FullscreenWindow() as window:
		while True:
			# Setup
			wheight = window.height
			wwidth  = window.width
			a = curtsies.FSArray(wheight,wwidth)

			# Divide the screen up into two, to keep it simple for now
			wheight_top_end    = int(wheight / 2)
			wheight_bottom_start = int(wheight / 2) + 1

			# Header
			header_text = 'telemetrise running on command: ' + command + ' ' + str(wheight) + 'x' + str(wwidth)
			a[0:1,0:len(header_text)] = [blue(header_text)]

			# Split the lines by newline, then reversed and zip up with line 2 to halfway.
			if command_output != '':
				lines = command_output.split('\r\n')
				for i, line in zip(reversed(range(2,wheight_top_end)), reversed(lines)):
					a[i:i+1, 0:len(line)] = [line]

			# We're done, now render!
			#write_to_logfile(a)
			window.render_to_terminal(a)

			# Now read input from main spawn
			char = None
			# 'while' keeps it line-oriented for reasonable performance...
			while char != '\n':
				try:
					char=pexpect_session.read_nonblocking(timeout=1)
				except pexpect.EOF:
					command_output += 'EOF'
				except:
					command_output += '?'
				if char:
					command_output += char.decode('utf-8')

command = 'ping -c100 google.com'
logfile = open('outfile','w')

def write_to_logfile(msg):
	global logfile
	logfile.write(str(msg) + '\n')
	logfile.flush()

if __name__ == '__main__':
	main(command)
