from ratBerryPi.resources import Pump, Valve, ResourceLocked
import RPi.GPIO as GPIO
import time

class BaseRewardModule:
    """
    a base class for all reward modules
    any class defining a reward module should inherit from this class
    """
    def __init__(self, name, pump:Pump, valve:Valve, dead_volume:float = 1):
        self.name = name
        self.pump = pump
        self.valve = valve
        self.dead_volume = dead_volume

    @property
    def pump_trigger(self):
        raise NotImplementedError("The pump_trigger property must be specified for lick triggered reward delivery")

    def trigger_reward(self, amount:float, force:bool = False, triggered = False, 
                       sync = False, post_delay = 1):
        """
        trigger reward delivery

        Args:
        -----
        amount: float
            the total amount of reward to be delivered in mLs
        force: bool
            flag to force reward delivery even if the pump is in use
        triggered: bool
            flag to deliver reward in triggered mode
        sync: bool
            flag to deliver reward synchronously. if set to true this function is blocking
            NOTE: triggered reward delivery is not supported when delivering reward synchronously
        post_delay: float
            amount of time in seconds to wait after reward delivery to ensure the entire reward amount
            is has been delivered. setting this value too small will result in less reward being delievered
            than requested
        """
        
        if force and self.pump.thread: 
            # if forcing stop any running reward delivery threads
            if self.pump.thread.running:
                self.pump.thread.stop()
        elif self.pump.thread:
            if self.pump.thread.running:
                raise ResourceLocked("Pump In Use")

        if sync:
            if triggered:
                raise ValueError("cannot deliver lick-triggered reward synchronously")
            else:
                acquired = self.acquire_locks()
                if acquired:
                    self.valve.open() # if make sure the valve is open before delivering reward
                    # make sure the fill valve is closed if the pump has one
                    if hasattr(self.pump, 'fillValve'): self.pump.fillValve.close()
                    # deliver the reward
                    self.pump.move(amount, force = force, direction = 'forward')
                    # wait then close the valve
                    time.sleep(post_delay)
                    self.valve.close()
                    # release the locks
                    self.release_locks()

        else: # spawn a thread to deliver reward asynchronously
            self.pump.async_pump(amount, triggered, close_fill = True, 
                                 valve = self.valve, direction = 'forward',
                                 trigger_source = self, post_delay = post_delay)

    def fill_line(self, amount:float = None, refill:bool = True, post_delay:float = 1):
        
        if amount is None: amount = self.dead_volume
        acquired = self.acquire_locks()
        if acquired:
            while amount>0:
                self.valve.close()
                if refill and hasattr(self.pump, 'fillValve'):
                    # if the syringe is not full refill it
                    if not self.pump.at_max_pos:
                        self.pump.fillValve.open()
                        self.pump.ret_to_max()
                        # wait then close the fill valve
                        time.sleep(post_delay)
                        self.pump.fillValve.close()
                # if the remaining/requested amount is more then available
                if not self.pump.is_available(amount):
                    # set the amount to be dispensed in the current iteration as the volume in the syringe
                    dispense_vol = self.pump.vol_left - .1 # for safety discount .1 mL so we don't come close to the end
                    if not hasattr(self.pump, 'fillValve'):
                        raise ValueError("the requested amount is greater than the volume left in the syringe and no fill valve has been specified to refill intermittently ")
                else: # if the remaining/requested amount is available set dispense volume accordingly
                    dispense_vol = amount
                self.valve.open()
                self.pump.move(dispense_vol, direction = 'forward')
                # wait then close the valve
                time.sleep(post_delay)
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
        fill_valve_reserved = self.pump.fillValve.lock.acquire(False) if hasattr(self.pump, 'fillValve') else True 
        return pump_reserved and valve_reserved and fill_valve_reserved
    
    def release_locks(self):
        """
        release all locks
        """

        self.valve.lock.release()
        if hasattr(self.pump, 'fillValve'):
            self.pump.fillValve.lock.release()
        self.pump.lock.release()

    def __del__(self):
        GPIO.cleanup()