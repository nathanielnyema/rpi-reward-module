from ratBerryPi.resources import Pump, Valve, ResourceLocked
from ratBerryPi.resources.pump import Direction
import RPi.GPIO as GPIO
import time
from abc import ABC, abstractmethod
import typing

class BaseRewardModule(ABC):
    """
    a base class for all reward modules
    any class defining a reward module should inherit from this class
    """
    def __init__(self, name, parent, pump:Pump, valvePin:typing.Union[int, str], 
                 dead_volume:float = 1, post_delay:float = 0.5, config:dict = {}):
        self.parent = parent
        self.name = name
        self.pump = pump
        self.post_delay = post_delay
        self.valve = Valve(f"{self.name}-valve", self, valvePin)
        self.dead_volume = dead_volume
        self.load_from_config(config)
        self.logger = self.parent.logger

    @abstractmethod
    def load_from_config(self, config: dict):
        ...

    def trigger_reward(self, amount:float, post_delay:float = None) -> None:
        """
        trigger reward delivery

        Args:
        -----
        amount: float
            the total amount of reward to be delivered in mLs
        post_delay: float
            amount of time after pump actuation to wait before closing the valve 
            [default = self.post_delay]
        """

        if not post_delay:
            post_delay = self.post_delay
        
        if not amount > 0:
            acquired = self.acquire_locks()
            if acquired:
                # prep the pump    
                self.prep_pump()
                self.valve.open() # if make sure the valve is open before delivering reward
                # make sure the fill valve is closed if the pump has one
                if self.pump.hasFillValve: self.pump.fillValve.close()
                # deliver the reward
                self.pump.move(amount, direction = Direction.FORWARD)
                # wait then close the valve
                time.sleep(post_delay)
                self.valve.close()
                # release the locks
                self.release_locks()
        else:
            self.logger.info("delivered 0 mL reward")

    def prep_pump(self):
        if self.pump.direction == Direction.BACKWARD and self.pump.hasFillValve:
            self.valve.close()
            self.pump.fillValve.open()
            self.pump.move(.05 * self.pump.syringe.mlPerCm, Direction.FORWARD)

    def empty_line(self, amount:float = None):

        assert self.pump.hasFillValve, "must have a fill valve to empty a line"
        if amount is None: amount = self.dead_volume
        acquired = self.acquire_locks()
        if acquired:
            while amount>0:
                self.pump.fillValve.close()
                self.valve.open()
                if not self.pump.at_max_pos: self.pump.ret_to_max()
                self.valve.close()
                self.pump.fillValve.open()
                _amt = max(self.pump.vol_left - 0.01 * self.pump.syringe.volume, 0)
                self.pump.move(_amt, Direction.FORWARD)
                amount -= _amt
            self.pump.fillValve.close()
            self.release_locks()


    def fill_line(self, amount:float = None, refill:bool = True):
        
        if amount is None: amount = self.dead_volume
        acquired = self.acquire_locks()
        if acquired:
            while amount>0:
                self.valve.close()
                if refill and self.pump.hasFillValve:
                    # if the syringe is not full refill it
                    if not self.pump.at_max_pos:
                        self.pump.fillValve.open()
                        self.pump.ret_to_max()
                        # wait then close the fill valve
                        self.pump.move(.1 * self.pump.syringe.mlPerCm, Direction.FORWARD)
                        time.sleep(self.post_delay)
                        self.pump.fillValve.close()
                # if the remaining/requested amount is more then available
                if not self.pump.is_available(amount):
                    self.logger.debug(amount)
                    # set the amount to be dispensed in the current iteration as the volume in the syringe
                    dispense_vol = self.pump.vol_left - .1 # for safety discount .1 mL so we don't come close to the end
                    if not self.pump.hasFillValve:
                        raise ValueError("the requested amount is greater than the volume left in the syringe and no fill valve has been specified to refill intermittently ")
                else: # if the remaining/requested amount is available set dispense volume accordingly
                    dispense_vol = amount
                self.valve.open()
                self.pump.move(dispense_vol, direction = Direction.FORWARD)
                # wait then close the valve
                time.sleep(self.post_delay)
                self.valve.close()
                amount = amount - dispense_vol
            # release the locks
            self.release_locks()

    def acquire_locks(self):
        """
        pre-acquire locks on shared resources

        Args:
        -----
        blocking: bool
            whether or not to temporarily block execution until
            each lock is acquired or a timeout is reached
        timeout: float
            timeout period to wait if blocking is true
        """
        pump_reserved = self.pump.lock.acquire(False) 
        valve_reserved = self.valve.lock.acquire(False)
        fill_valve_reserved = self.pump.fillValve.lock.acquire(False) if self.pump.hasFillValve else True 
        return pump_reserved and valve_reserved and fill_valve_reserved
    
    def release_locks(self):
        """
        release all locks
        """

        self.valve.lock.release()
        if self.pump.hasFillValve:
            self.pump.fillValve.lock.release()
        self.pump.lock.release()

    def __del__(self):
        GPIO.cleanup()