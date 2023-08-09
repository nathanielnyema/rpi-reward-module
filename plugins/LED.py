import RPi.GPIO as GPIO


class LED:
    #TODO: need s function to flash the led for a specified amount of time
    def __init__(self, LEDPin):
        self.LEDPin = LEDPin
        GPIO.setup(self.LEDPin, GPIO.OUT)
    
    def on(self, LEDPin):
        GPIO.output(self.LEDPin, GPIO.HIGH)
    
    def off(self, LEDPin):
        GPIO.output(self.LEDPin, GPIO.LOW)