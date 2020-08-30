#!/usr/bin/python3
# -*- coding: utf-8 -*-

from datetime import datetime
import pyaudio
import sys
import os
import logging
import threading
import argparse

# RUN_ON_RASPBERRY_PI = os.uname()[4][:3] == 'arm'
FONT_DIRECTORY = os.path.join(os.path.dirname(__file__), 'assets/fonts/')
DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), 'data/')
FONT_SIZE = 20

FORMAT = pyaudio.paInt16  # 16-bit resolution
CHANNELS = 1              # mono is fine?
FRAME_RATE = 44100        # this is the default for PyAudio
FRAMES_PER_BUFFER = 9216  # how much audio data we read/write at a time
RECORD_SECONDS = 61       # how many seconds we of audio we keep in memory. determines max delay
MIN_DELAY = 0
DEFAULT_DELAY = MIN_DELAY
MAX_DELAY= RECORD_SECONDS - 1

LOG_DATE_FORMAT = "%I:%M:%S %p"

formatter = logging.Formatter('%(asctime)s_%(name)s_%(levelname)s - %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)

fh = logging.FileHandler(DATA_DIRECTORY + 'radiodelay.log', 'a')
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)

logger = logging.getLogger('radiodelay_logger')

logger.setLevel(logging.DEBUG)
logger.addHandler(ch)
logger.addHandler(fh)

parser = argparse.ArgumentParser()
parser.add_argument('--delay',       '-d', type=int, required=False, choices=range(0, RECORD_SECONDS), default=DEFAULT_DELAY, help="set the initial delay in seconds")
parser.add_argument('--ssd',         '-s', type=int, required=False, choices=(0,1),                    default=0,             help="run with ssd1306 display and tactile buttons (on pi zero)")
parser.add_argument('--interactive', '-i', type=int, required=False, choices=(0,1),                    default=0,             help="accept command line input")

args = parser.parse_args()

if args.ssd:
	import board
	import busio
	import digitalio
	from PIL import Image, ImageDraw, ImageFont
	import adafruit_ssd1306

if args.interactive:
	import queue
	
	EXIT_COMMAND = 'quit'
	INSTRUCTIONS = "type desired delay in seconds ({} - {}) or '{}' to quit".format(MIN_DELAY, MAX_DELAY, EXIT_COMMAND)
	
	"""
	small thread to handle keyboard input on desktop
	as seen here: https://stackoverflow.com/questions/5404068/how-to-read-keyboard-input/53344690#53344690
	"""
	def read_kbd_input(input_queue):
		print(INSTRUCTIONS)
		
		while (True):
			input_str = input()
			input_queue.put(input_str)
		
"""
RadioDelay Class
"""
class RadioDelay(object):
	def __init__(self):
		logger.info('radiodelay.py inited at {}'.format(datetime.now().strftime("%m/%d/%Y %I:%M %p")))
	
	def init_streams(self):
		# desired delay in seconds. initialized by command line arg or its default
		self.delay_seconds = args.delay
		
		# number of recording chunks we keep in memory
		self.buffer_chunks = int(RECORD_SECONDS * FRAME_RATE / FRAMES_PER_BUFFER)
		
		# our loop iterator
		self.buffer_index = 0
		
		# the number of recorded chunks back we start playback
		self.delay_chunks = int(self.delay_seconds * FRAME_RATE / FRAMES_PER_BUFFER)
		
		# init our array of recorded chunks with empty bytes
		self.buffer_frames = ['\x00' * FRAMES_PER_BUFFER] * self.buffer_chunks
		
		self.pa = pyaudio.PyAudio()
		
		# init our input and output streams
		self.input_stream = self.pa.open(
			format=FORMAT,
			channels=CHANNELS,
			rate=FRAME_RATE,
			input=True,
			frames_per_buffer=FRAMES_PER_BUFFER
		)
		
		self.output_stream = self.pa.open(
			format=FORMAT,
			channels=CHANNELS,
			rate=FRAME_RATE,
			output=True,
			frames_per_buffer=FRAMES_PER_BUFFER
		)
	
	def init_ssd(self):
		self.display = self.init_display()
		
		self.buttons = self.init_buttons()
		
		self.display_text(3, 5, 'radiodelay {}'.format(self.delay_seconds))

		#logger.debug('default input device: {}'.format(self.pa.get_default_input_device_info()))
		#logger.debug('default output device: {}'.format(self.pa.get_default_output_device_info()))
	
	"""
	set up ssd1306 display and return dict with display and pil objects
	"""
	def init_display(self):
	
		# Create the SPI interface.
		spi = busio.SPI(board.SCK, MOSI=board.MOSI)

		# define display connections
		reset_pin = digitalio.DigitalInOut(board.D4)
		cs_pin = digitalio.DigitalInOut(board.D5)
		dc_pin = digitalio.DigitalInOut(board.D6)

		# Create the SSD1306 OLED class.
		disp = adafruit_ssd1306.SSD1306_SPI(128, 32, spi, dc_pin, reset_pin, cs_pin)

		# Clear display.
		disp.fill(0)
		disp.show()

		# Create blank image for drawing.
		# Make sure to create image with mode '1' for 1-bit color.
		width = disp.width
		height = disp.height
		image = Image.new("1", (width, height))
		
		# Get drawing object to draw on image.
		draw = ImageDraw.Draw(image)
		
		# Alternatively load a TTF font.  Make sure the .ttf font file is in the
		# Some other nice fonts to try: http://www.dafont.com/bitmap.php
		font = ImageFont.truetype(FONT_DIRECTORY + 'bold.ttf', FONT_SIZE)
		
		return {
			'display': disp,
			'canvas':  image,
			'draw':    draw,
			'font':    font
		}
	
	"""
	set up GPIO buttons and return dict with button refs by name
	"""
	def init_buttons(self):
		button_left = digitalio.DigitalInOut(board.D23)
		button_left.direction = digitalio.Direction.INPUT
		button_left.pull = digitalio.Pull.UP

		button_right = digitalio.DigitalInOut(board.D24)
		button_right.direction = digitalio.Direction.INPUT
		button_right.pull = digitalio.Pull.UP
		
		return {
			'left':  button_left,
			'right': button_right
		}
	
	"""
	write line of text to display and display
	"""
	def display_text(self, x, y, text):
		
		display = self.display['display']
		draw = self.display['draw']
		font = self.display['font']
		canvas = self.display['canvas']
		
		draw.rectangle((0, 0, display.width, display.height), outline=0, fill=0)
		draw.text((x, y), text, font=font, fill=255)
		
		display.image(canvas)
		display.show()
	
	"""
	iteration of loop to check buttons
	"""
	def buttons_loop(self):
		
		new_delay = None
		
		if not self.buttons['left'].value:
			new_delay = self.delay_seconds - 1
		
		if not self.buttons['right'].value:
			new_delay = self.delay_seconds + 1
		
		if new_delay is not None and new_delay >= MIN_DELAY and new_delay <= MAX_DELAY:
			logger.debug('setting new delay of {}'.format(new_delay))
			
			self.delay_seconds = new_delay
			self.delay_chunks = int(self.delay_seconds * FRAME_RATE / FRAMES_PER_BUFFER)
			self.display_text(3, 5, 'radiodelay {}'.format(self.delay_seconds))
	
	"""
	single iteration over our recorded chunks list
	  add a new chunk of input and output an offset chunk
	"""
	def init_streams_loop(self):
		while True:
			self.streams_loop()
	
	def streams_loop(self):
		try:
			data = self.input_stream.read(FRAMES_PER_BUFFER)
		except IOError as ex:
			logger.info('IOError of with number {} in streams_loop: {}'.format(ex.errno, ex))
		
			if ex.errno != pyaudio.paInputOverflowed:
				raise
			data = '\x00' * FRAMES_PER_BUFFER
		
		self.buffer_frames[self.buffer_index] = data
		
		data = self.buffer_frames[self.buffer_index - self.delay_chunks]
		
		self.output_stream.write(data, FRAMES_PER_BUFFER)
		
		self.buffer_index = self.buffer_index + 1
		
		if (self.buffer_index >= self.buffer_chunks):
			self.buffer_index = 0
	
	"""
	handle keyboard input after enter
	"""
	def input_loop(self):
		if (input_queue.qsize() > 0):
			
			input_str = input_queue.get()
			
			if input_str == EXIT_COMMAND:
				print('quitting radiodelay.py')
				self.kill()
				return
			
			try:
				new_delay = int(input_str)
				
				if new_delay < MIN_DELAY or new_delay > MAX_DELAY:
					raise
				
				self.delay_seconds = new_delay
				self.delay_chunks = int(self.delay_seconds * FRAME_RATE / FRAMES_PER_BUFFER)
				
				print('delay set to {} seconds'.format(self.delay_seconds))
			
			except:
				print('invalid delay. try again.')
	
	"""
	cleanup and exit
	"""
	def kill(self):
		logger.info('radiodelay.py exiting at {}'.format(datetime.now().strftime("%m/%d/%Y %I:%M %p")))
		
		self.input_stream.stop_stream()
		self.output_stream.stop_stream()
	
		self.input_stream.close()
		self.output_stream.close()
		
		self.pa.terminate()
		
		sys.exit(0)

if __name__ == '__main__':
	
	rd = RadioDelay()
	
	rd.init_streams()
	
	streams_thread = threading.Thread(target=rd.init_streams_loop, args=(), daemon=True)
	streams_thread.start() 
	
	loop_methods = []
	
	if args.interactive:
		input_queue = queue.Queue()
		input_thread = threading.Thread(target=read_kbd_input, args=(input_queue,), daemon=True)
		input_thread.start()
		
		loop_methods.append(rd.input_loop)
	
	if args.ssd:
		rd.init_ssd()
		
		loop_methods.append(rd.buttons_loop)
	
	while True:
		for method in loop_methods:
			method()
	
	rd.kill()
