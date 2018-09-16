import pyautogui
import random
import time

print('Press Ctrl-C to quit.')

delay = 5 #Time of delay in seconds between movements
screenX, screenY = pyautogui.size() #Define screen resolution
monitorCount = 1 #Define monitors quantity

try:
    #Fall in to loop. Each iteration is a new movement
    while True:
        #Define endpoint of movement
        endPositionX, endPositionY = (random.randint(0, screenX) * monitorCount, random.randint(0, screenY))
        #Move mouse to coordinates
        pyautogui.moveTo(endPositionX, endPositionY, 3, pyautogui.easeInOutQuad)
        #Wait for delay after movement
        time.sleep(delay)
except KeyboardInterrupt:
    print('\n')
