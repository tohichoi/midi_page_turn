import pygame
import pygame.midi
from time import sleep
import subprocess
import time
import sys
from yaspin import yaspin
from yaspin.spinners import Spinners


def sendkey(vkcode):
	subprocess.check_call(['powershell', '.\\Send-KeyPress.ps1', '-KeyCode', vkcode])

def midi_page_turn():
	inputdevice={}
	outputdevice={}

	pygame.init()
	pygame.midi.init()

	print('')
	print('{0:3s}   {1:7s} {2:10s} {3:^50s}'.format('ID', 'TYPE', 'STATUS', 'NAME'))
	print('-'*79)

	devlist=[]

	for i in range(pygame.midi.get_count()):
		ret=pygame.midi.get_device_info(i)
		# (interf, name, input, output, opened)
		typestr=''
		if ret[2] and ret[3]:
			typestr="IN/OUT"
		elif ret[2]:
			typestr="IN"
		elif ret[3]:
			typestr="OUT"

		print('[{0:d}]   {1:7s} {2:10s} {3:^50s}'.format(i, typestr, ("OK" if ret[4] else "NA"), ret[1].decode("utf-8")))

		devlist.append((i,)+tuple(ret))

	# print(devlist)
	print('-'*79)
	print('')
	
	inputdev=list(filter(lambda x : x[3]==1, devlist))
	# print(inputdev)
	outputdev=list(filter(lambda x : x[4]==1, devlist))
	# print(outputdev)
	
	# 'opened' means we opended, not system.
	# opened_inputdev=list(filter(lambda x : x[5]==1, inputdev))
	opened_inputdev=inputdev
	ninput=len(opened_inputdev)
	if ninput < 1:
		print('No input device is available\n')
		pygame.midi.quit()
		sys.exit(1)
	elif ninput == 1:
		print('Using the first opened device : {}\n'.format(opened_inputdev[0][2].decode('utf-8')))
		inport=opened_inputdev[0][0]
	else:
		while True:
			idlist=[]
			for dev in opened_inputdev:
				idlist.append(dev[0])
				print(f'[{dev[0]}] {dev[2]}')
			ret=input('Select input devices : ').strip()
			if int(ret) in idlist:
				inport=int(ret)
				break
			else:
				print('Invalid input: {ret}. Please retry')

	print('Waiting for MIDI control messages ... \n')

	# print('[{0:d}] : {1}'.format(i, ret))

	# print(inputdevice)
	# print(outputdevice)

	# inport=1

	LEFT_PEDAL=67
	MID_PEDAL=66
	VK_LEFT='0x25'
	VK_RIGHT='0x27'
	VK_UP='0x26'
	VK_DOWN='0x28'
	# control code : sendkey at that time, keytype
	# LEFT-MOST Pedal is more comfortable for NEXT page.
	ccdata={LEFT_PEDAL:[True, VK_DOWN], MID_PEDAL:[True, VK_UP]}

	try:
		# spinner=yaspin(Spinners.bouncingBall, color="blue", on_color="on_yellow",)
		spinner=yaspin(text='  🎹 Receiving MIDI data')

		midi_in=pygame.midi.Input(inport)
		
		while True:
			for event in pygame.event.get():
				if event.type == pygame.QUIT:
					# 'finally' is executed
					sys.exit()

			sleep(0)

			if not midi_in.poll():
				spinner.stop()
				continue

			spinner.start()
			
			# status, controller, value, ?, ?
			# [[176, 67, 127, 0], 41834]
			data=midi_in.read(100)

			for d in data:
				st=d[0][0]
				cc=d[0][1]
				val=d[0][2]

				# control message
				# 0b1011CCCC : 1011 : control, CCCC: channel
				# print('{:b}'.format(st & 0b10110000))
				if (st >> 4 & 0b1011) is not 0b1011:
					continue

				if cc not in ccdata.keys():
					break

				# print(d)

				# print(f'ControlCode : {cc}, Value: {val}')
				if val > 0:
					if ccdata[cc][0]:
						sendkey(ccdata[cc][1])
						ccdata[cc][0]=False
						# print('-'*20)
						# print('')
						# spinner.stop()
						spinner.write('  🎼 {0} {1:d}'.format(('NEXT' if cc==LEFT_PEDAL else "PREV"), int(time.time())))
						# spinner.start()
						# spinner.ok('✔')
						# print('-'*20)
				else: # val is zero (means end of control message)
					ccdata[cc][0]=True
	finally:
		print("\nClosing ... ", end='')
		# sleep(1)
		# if pygame.get_init():
		# 	pygame.quit()
		if pygame.midi.get_init():
			midi_in.close()
			pygame.midi.quit()
		print("Done")


midi_page_turn()