#!/usr/bin/env python3
"""
Fellow Stagg EKG Pro - Complete Control Class
Reverse-engineered BLE protocol for the configuration options of
Fellow Stagg EKG Pro kettle
"""

import asyncio
from bleak import BleakClient
from enum import Enum
from typing import Optional, Callable
import logging

MAIN_CONFIG_UUID = "2291c4b5-5d7f-4477-a88b-b266edb97142"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ClockMode(Enum):
    """Clock display modes"""
    OFF = 0
    DIGITAL = 1
    ANALOG = 2

class Units(Enum):
    """Temperature units"""
    CELSIUS = 0x17
    FAHRENHEIT = 0x15

class ScheduleMode(Enum):
    """Schedule modes"""
    OFF = 0
    ONCE = 1
    DAILY = 2

class Language(Enum):
    """Menu languages"""
    ENGLISH = 0x00
    FRENCH = 0x01
    SPANISH = 0x02
    SIMPLIFIED_CHINESE = 0x03
    TRADITIONAL_CHINESE = 0x04
    #KOREAN = ?
    #JAPANESE = ?

class StaggEKGPro_Config:
    """
    Fellow Stagg EKG Pro Config Controller
    This class handles configuration bytes of the kettle

    BLE Protocol Structure (17 bytes):
        - Byte 0: Status flags
            * Bit 3 (0x08): Schedule enabled (0=OFF, 1=ON)
        - Byte 1: Control flags
            * Bit 1 (0x02): Units (0=Fahrenheit, 1=Celsius)
            * Bit 3 (0x08): Pre-boil (0=OFF, 1=ON)
        - Byte 2-3: Altitude (meters, split across bytes with 0x80 offset in byte 3)
        - Byte 4: Target temperature (multiply by 2 for °C)
        - Byte 5: Unknown/status
        - Byte 6: Schedule target temperature (multiply by 2 for °C, 0xc0=disabled)
        - Byte 7: Unknown/status
        - Byte 8: Schedule minutes (0-59)
        - Byte 9: Schedule hours (0-23, 24-hour format)
        - Byte 10: Clock minutes (0-59)
        - Byte 11: Clock hours (0-23, 24-hour format)
        - Byte 12: Clock mode (0=OFF, 1=DIGITAL, 2=ANALOG)
        - Byte 13: Hold time in minutes (0-63, 0=OFF)
        - Byte 14: Chime volume (0=OFF, 1-10=volume level)
        - Byte 15: Languages
        - Byte 16: Counter (increments with each write)
            * Bit 3 (0x08): Schedule mode (1=ONCE, 0=DAILY) -> can only enable once through BLE.

    """

    def __init__(self, address: str):
        """
        Initialize the Stagg EKG Pro controller

        Args:
            address: BLE MAC address or UUID of the kettle
        """
        self.address = address
        self.MAIN_CONFIG_UUID = MAIN_CONFIG_UUID
        self.client: Optional[BleakClient] = None
        self._state_data: Optional[bytearray] = None
        self._notification_callback: Optional[Callable] = None
        self._counter: int = 0

    async def connect(self) -> bool:
        """
        Connect to the kettle

        Returns:
            True if connected successfully
        """
        try:
            self.client = BleakClient(self.address)
            await self.client.connect()

            if self.client.is_connected:
                logger.info(f"✅ Connected to Stagg EKG Pro at {self.address}")

                # Start listening to notifications
                await self.client.start_notify(
                    self.MAIN_CONFIG_UUID,
                    self._handle_notification
                )

                # Read initial state
                await self.refresh_state()
                return True
            return False

        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False

    async def disconnect(self):
        """Disconnect from the kettle"""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            logger.info("🔌 Disconnected from kettle")

    def _handle_notification(self, sender, data: bytearray):
        """
        Handle BLE notifications from the kettle

        Note: Notifications are only sent when settings are changed via the kettle's
        menu interface, not during heating or temperature changes.
        """
        self._state_data = bytearray(data)
        self._counter = data[16]

        logger.debug(f"📡 Notification received: {data.hex()}")

        # Call user callback if registered
        if self._notification_callback:
            self._notification_callback(self.get_state())

    def set_notification_callback(self, callback: Callable):
        """
        Set a callback function to be called when settings updates are received

        Note: Callbacks are only triggered when settings are changed via the kettle's
        menu interface (clock, chime, target temp). They are NOT triggered during
        heating or temperature changes.

        Args:
            callback: Function that takes a state dict as parameter
        """
        self._notification_callback = callback

    async def refresh_state(self):
        """Read the current state from the kettle"""
        if not self.client or not self.client.is_connected:
            raise RuntimeError("Not connected to kettle")

        data = await self.client.read_gatt_char(self.MAIN_CONFIG_UUID)
        self._state_data = bytearray(data)
        self._counter = data[16]
        logger.debug(f"📊 State refreshed: {data.hex()}")

    def get_state(self) -> dict:
        """
        Get the current state of the kettle

        Returns:
            Dictionary with current state values
        """
        if not self._state_data or len(self._state_data) < 17:
            return {}

        data = self._state_data

        # Parse temperature
        target_temp = data[4] / 2.0

        # Parse settings byte 1
        units = "celsius" if data[1] & 0x02 else "fahrenheit"
        pre_boil_enabled = bool(data[1] & 0x08)

        # Parse altitude
        altitude = self.get_altitude() or 0

        # Parse clock settings
        clock_minutes = data[10]
        clock_hours = data[11]
        clock_mode_val = data[12]

        if clock_mode_val == 0:
            clock_mode = "off"
        elif clock_mode_val == 1:
            clock_mode = "digital"
        elif clock_mode_val == 2:
            clock_mode = "analog"
        else:
            clock_mode = "unknown"

        # Parse hold time
        hold_time = data[13]

        # Parse chime volume
        chime_volume = data[14]

        return {
            'target_temperature': target_temp,
            'units': units,
            'pre_boil_enabled': pre_boil_enabled,
            'altitude_meters': altitude,
            'clock_mode': clock_mode,
            'clock_hours': clock_hours,
            'clock_minutes': clock_minutes,
            'clock_time': f"{clock_hours:02d}:{clock_minutes:02d}",
            'hold_time_minutes': hold_time,
            'hold_enabled': hold_time > 0,
            'chime_volume': chime_volume,
            'chime_enabled': chime_volume > 0,
            'raw_data': data.hex(),
            'counter': data[16]
        }

    async def _write_state(self, new_data: bytearray):
        """Internal method to write state to kettle"""
        if not self.client or not self.client.is_connected:
            raise RuntimeError("Not connected to kettle")

        # Increment counter
        new_data[16] = (self._counter + 1) & 0xFF

        await self.client.write_gatt_char(self.MAIN_CONFIG_UUID, bytes(new_data))
        logger.debug(f"✍️ Written: {new_data.hex()}")

        # Update our state
        self._state_data = new_data
        self._counter = new_data[16]

    # ========== Temperature Control ==========

    async def set_target_temperature(self, temp_celsius: float):
        """
        Set the target temperature

        Args:
            temp_celsius: Target temperature in Celsius (0-100)
        """
        if not self._state_data:
            await self.refresh_state()

        # Clamp temperature to valid range
        temp_celsius = max(0, min(100, temp_celsius))

        new_data = bytearray(self._state_data)
        new_data[4] = int(temp_celsius * 2)

        await self._write_state(new_data)
        logger.info(f"🎯 Target temperature set to {temp_celsius}°C")

    def get_target_temperature(self) -> Optional[float]:
        """Get the current target temperature in Celsius"""
        if not self._state_data:
            return None
        return self._state_data[4] / 2.0

    # ========== Units Control ==========

    async def set_units(self, units: Units):
        """
        Set temperature units

        Args:
            units: Units.CELSIUS or Units.FAHRENHEIT
        """
        if not self._state_data:
            await self.refresh_state()

        new_data = bytearray(self._state_data)

        # Preserve other bits in byte 1
        if units == Units.CELSIUS:
            new_data[1] |= 0x02  # Set bit 1
        else:
            new_data[1] &= ~0x02  # Clear bit 1

        await self._write_state(new_data)
        logger.info(f"🌐 Units set to {units.name}")

    def get_units(self) -> Optional[str]:
        """Get the current temperature units"""
        if not self._state_data:
            return None
        return "celsius" if self._state_data[1] & 0x02 else "fahrenheit"

    # ========== Clock Control ==========

    async def set_clock_mode(self, mode: ClockMode):
        """
        Set the clock display mode

        Args:
            mode: ClockMode.OFF, ClockMode.ANALOG, or ClockMode.DIGITAL
        """
        if not self._state_data:
            await self.refresh_state()

        new_data = bytearray(self._state_data)
        new_data[12] = mode.value

        await self._write_state(new_data)
        logger.info(f"🕐 Clock mode set to {mode.name}")

    async def set_clock_time(self, hours: int, minutes: int, mode: Optional[ClockMode] = None):
        """
        Set the clock time and optionally the display mode

        Args:
            hours: Hours in 24-hour format (0-23)
            minutes: Minutes (0-59)
            mode: Optional clock mode (keeps current mode if not specified)
        """
        if not self._state_data:
            await self.refresh_state()

        # Validate inputs
        if not (0 <= hours <= 23):
            raise ValueError("Hours must be between 0 and 23")
        if not (0 <= minutes <= 59):
            raise ValueError("Minutes must be between 0 and 59")

        new_data = bytearray(self._state_data)
        new_data[10] = minutes
        new_data[11] = hours

        if mode is not None:
            new_data[12] = mode.value

        await self._write_state(new_data)
        logger.info(f"🕐 Clock set to {hours:02d}:{minutes:02d}" +
                   (f" ({mode.name})" if mode else ""))

    def get_clock_time(self) -> Optional[tuple]:
        """
        Get the current clock time

        Returns:
            Tuple of (hours, minutes) or None
        """
        if not self._state_data or len(self._state_data) < 12:
            return None
        return (self._state_data[11], self._state_data[10])

    def get_clock_mode(self) -> Optional[str]:
        """
        Get the current clock mode

        Returns:
            "off", "digital", "analog", or None
        """
        if not self._state_data or len(self._state_data) < 13:
            return None

        mode_val = self._state_data[12]
        if mode_val == 0:
            return "off"
        elif mode_val == 1:
            return "digital"
        elif mode_val == 2:
            return "analog"
        return "unknown"

    # ========== Chime Control ==========

    async def set_chime_volume(self, volume: int):
        """
        Set the chime volume

        Args:
            volume: Volume level 0-10 (0 = off, 1-10 = volume level)
        """
        if not self._state_data:
            await self.refresh_state()

        # Clamp volume to valid range
        volume = max(0, min(10, volume))

        new_data = bytearray(self._state_data)
        new_data[14] = volume

        await self._write_state(new_data)

        if volume == 0:
            logger.info("🔔 Chime disabled")
        else:
            logger.info(f"🔔 Chime volume set to {volume}")

    def get_chime_volume(self) -> Optional[int]:
        """Get the current chime volume (0-10, where 0 = OFF)"""
        if not self._state_data:
            return None
        return self._state_data[14]

    # ========== Pre-boil Control ==========

    async def set_pre_boil(self, enabled: bool):
        """
        Enable or disable pre-boil feature

        Args:
            enabled: True to enable pre-boil, False to disable
        """
        if not self._state_data:
            await self.refresh_state()

        new_data = bytearray(self._state_data)

        if enabled:
            new_data[1] |= 0x08  # Set bit 3
        else:
            new_data[1] &= ~0x08  # Clear bit 3

        await self._write_state(new_data)
        logger.info(f"🔥 Pre-boil {'enabled' if enabled else 'disabled'}")

    def get_pre_boil(self) -> Optional[bool]:
        """Check if pre-boil is enabled"""
        if not self._state_data:
            return None
        return bool(self._state_data[1] & 0x08)

    # ========== Hold Time Control ==========

    async def set_hold_time(self, minutes: int):
        """
        Set hold temperature time

        Args:
            minutes: Hold time in minutes (0=OFF, 15-60 in 15-min increments)
                    Note: Kettle supports 0, 15, 30, 45, 60
        """
        if not self._state_data:
            await self.refresh_state()

        # Clamp to valid range
        minutes = max(0, min(60, minutes))

        new_data = bytearray(self._state_data)
        new_data[13] = minutes

        await self._write_state(new_data)

        if minutes == 0:
            logger.info("⏱️ Hold mode disabled")
        else:
            logger.info(f"⏱️ Hold time set to {minutes} minutes")

    def get_hold_time(self) -> Optional[int]:
        """Get the current hold time in minutes (0 = OFF)"""
        if not self._state_data:
            return None
        return self._state_data[13]

    # ========== Altitude Control ==========

    async def set_altitude(self, altitude_meters: int):
        """
        Set the altitude compensation level for boiling point calibration

        Args:
            altitude_meters: Altitude in meters (0-3000)

        Note: Kettle supports 30-meter increments. Values will be rounded
              to the nearest 30m automatically.
        """
        if not self._state_data:
            await self.refresh_state()

        # Clamp to safe range and round to 30m increments
        altitude_meters = max(0, min(3000, altitude_meters))
        quantized = round(altitude_meters / 30) * 30

        # Encode altitude in meters
        byte2 = quantized & 0xFF
        byte3 = 0x80 + ((quantized >> 8) & 0x7F)

        new_data = bytearray(self._state_data)
        new_data[2] = byte2
        new_data[3] = byte3

        await self._write_state(new_data)
        logger.info(f"🏔️ Altitude set to {quantized}m" +
                   (f" (rounded from {altitude_meters}m)" if quantized != altitude_meters else ""))

    def get_altitude(self) -> Optional[int]:
        """
        Get the current altitude compensation in meters

        Returns:
            Altitude in meters (rounded to nearest 30m), or None
        """
        if not self._state_data or len(self._state_data) < 4:
            return None

        byte2 = self._state_data[2]
        byte3 = self._state_data[3]
        altitude = ((byte3 & 0x7F) << 8) | byte2

        # Round to nearest 30m for consistency
        return round(altitude / 30) * 30

    def decode_schedule_time(self, data: bytearray):
        """Decode (hour, minute) from bytes 8–9."""
        minute = data[8]
        hour = data[9]
        return hour, minute

    def encode_schedule_time(self, hour: int, minute: int = 0):
        """Return bytes (8, 9) for the given time."""
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Hour must be 0–23 and minute 0–59")
        return bytes([minute, hour])

    async def set_schedule(self, mode: ScheduleMode, hour: int = 0, minute: int = 0, temp_celsius: float = 85):
        """
        Set the schedule mode, time, and temperature

        Args:
            mode: ScheduleMode.OFF, ONCE, or DAILY
            hour: Hour in 24-hour format (0-23)
            minute: Minute (0-59)
            temp_celsius: Schedule target temperature in Celsius (0-100)

        Note: Changing between ONCE and DAILY requires a two-step process:
              1. Disable schedule
              2. Re-enable with new mode
        """
        if not self._state_data:
            await self.refresh_state()

        if mode == ScheduleMode.OFF:
            # Disable schedule
            new_data = bytearray(self._state_data)
            new_data[0] &= ~0x08      # Clear schedule enable bit (bit 3 of byte 0)
            new_data[6] = 0xc0        # Clear schedule temperature
            new_data[8] = 0x00        # Clear minutes
            new_data[9] = 0x00        # Clear hours

            await self._write_state(new_data)
            logger.info("📅 Schedule disabled")
            return

        # Validate inputs for ONCE/DAILY modes
        if not (0 <= hour <= 23):
            raise ValueError("Hour must be between 0 and 23")
        if not (0 <= minute <= 59):
            raise ValueError("Minutes must be between 0 and 59")
        temp_celsius = max(0, min(100, temp_celsius))

        # Get current mode to determine if we need the two-step process
        current_mode = self.get_schedule_mode()
        needs_disable = current_mode in ["once", "daily"] and current_mode != mode.name.lower()

        if needs_disable:
            # Step 1: Disable schedule first
            temp_data = bytearray(self._state_data)
            temp_data[0] &= ~0x08
            temp_data[6] = 0xc0
            temp_data[8] = 0x00
            temp_data[9] = 0x00
            temp_data[16] = (temp_data[16] + 1) & 0xFF
            await self._write_state(temp_data)
            await asyncio.sleep(0.3)  # Brief pause for kettle to process

        # Step 2: Enable schedule with new parameters
        new_data = bytearray(self._state_data)
        new_data[0] |= 0x08                    # Set schedule enable bit
        new_data[6] = int(temp_celsius * 2)    # Schedule temperature
        new_data[8] = minute                   # Schedule minutes
        new_data[9] = hour                     # Schedule hours

        # Set mode bit in byte 16, bit 3
        # Bit 3 = 1 for ONCE, Bit 3 = 0 for DAILY
        if mode == ScheduleMode.ONCE:
            new_data[16] = (new_data[16] | 0x08) + 1   # Set bit 3
        else:  # DAILY
            new_data[16] = (new_data[16] & ~0x08) + 1  # Clear bit 3

        await self._write_state(new_data)
        logger.info(f"📅 Schedule set to {mode.name} at {hour:02d}:{minute:02d}, {temp_celsius}°C")


    def get_schedule(self) -> dict:
        """
        Get the current schedule settings

        Returns:
            Dictionary with schedule state
        """
        if not self._state_data or len(self._state_data) < 17:
            return {}

        data = self._state_data

        # Check if schedule is enabled (bit 3 of byte 0)
        schedule_enabled = bool(data[0] & 0x08)

        if not schedule_enabled:
            return {
                'schedule_mode': 'off',
                'schedule_enabled': False,
                'schedule_temperature': None,
                'schedule_hour': None,
                'schedule_minute': None,
                'schedule_time': None
            }

        # Decode schedule mode from byte 16, bit 3
        mode_bit = (data[16] >> 3) & 1
        mode = "once" if mode_bit == 1 else "daily"

        # Decode schedule temperature from byte 6
        schedule_temp = data[6] / 2.0

        # Decode schedule time from bytes 8-9
        schedule_minute = data[8]
        schedule_hour = data[9]

        return {
            'schedule_mode': mode,
            'schedule_enabled': True,
            'schedule_temperature': schedule_temp,
            'schedule_hour': schedule_hour,
            'schedule_minute': schedule_minute,
            'schedule_time': f"{schedule_hour:02d}:{schedule_minute:02d}"
        }


    def get_schedule_mode(self) -> Optional[str]:
        """
        Get the current schedule mode

        Returns:
            "off", "once", "daily", or None
        """
        if not self._state_data or len(self._state_data) < 17:
            return None

        # Check if schedule is enabled
        if not (self._state_data[0] & 0x08):
            return "off"

        # Check bit 3 of byte 16
        mode_bit = (self._state_data[16] >> 3) & 1
        return "once" if mode_bit == 1 else "daily"

    async def set_language(self, language: Language):
        """
        Set the kettle's language.

        Args:
            language: A Language enum member
        """
        if not self._state_data:
            await self.refresh_state()

        if not isinstance(language, Language):
            raise ValueError(f"Invalid language: {language}. Must be a Language enum.")

        new_data = bytearray(self._state_data)
        new_data[15] = language.value
        await self._write_state(new_data)

        logger.info(f"🌐 Language set to {language.name.title()}")

    def get_language(self) -> Optional[Language]:
        """
        Get the current language of the kettle.

        Returns:
            Language enum member, or None if unknown
        """
        if not self._state_data or len(self._state_data) < 16:
            return None

        byte15 = self._state_data[15]
        try:
            return Language(byte15)
        except ValueError:
            return None
    async def turn_on_smart(self, temp_celsius: float = None):
        """
        Turns the kettle on without losing your existing schedule.

        Mechanism:
        1. Backs up your current schedule (e.g., Daily at 7:00 AM).
        2. Overwrites schedule to 1 minute in the future (Trigger).
        3. Waits for the kettle to activate (approx 60s).
        4. Restores your original schedule.
        """
        if not self._state_data:
            await self.refresh_state()

        # --- STEP 1: BACKUP ---
        # Save the current schedule state so we don't lose it
        backup_sched = self.get_schedule()
        logger.info(f"💾 Backup: Saved existing schedule ({backup_sched.get('schedule_mode')} @ {backup_sched.get('schedule_time')})")

        # --- STEP 2: TRIGGER (The "Unlock") ---
        # Calculate 'Now + 1 minute'
        current_h = self._state_data[11]
        current_m = self._state_data[10]

        trigger_m = current_m + 1
        trigger_h = current_h

        # Handle time rollovers (e.g., 12:59 -> 13:00)
        if trigger_m >= 60:
            trigger_m = 0
            trigger_h += 1
        if trigger_h >= 24:
            trigger_h = 0

        target_temp = temp_celsius if temp_celsius else (self._state_data[4] / 2.0)

        logger.info(f"🚀 Triggering: Scheduling start for {trigger_h:02d}:{trigger_m:02d}...")

        # Set temporary 'ONCE' schedule to force start
        await self.set_schedule(
            mode=ScheduleMode.ONCE,
            hour=trigger_h,
            minute=trigger_m,
            temp_celsius=target_temp
        )

        # --- STEP 3: WAIT FOR ACTIVATION ---
        # We must wait for the kettle to actually turn on.
        # If we restore the schedule too fast, the kettle will cancel the trigger.
        logger.info("⏳ Waiting 65 seconds for kettle to activate...")

        # Optional: You could poll get_state() here to return early if temp starts rising
        await asyncio.sleep(65)

        # --- STEP 4: RESTORE ---
        # Put things back exactly how you found them
        if backup_sched.get('schedule_enabled'):
            # Convert string mode back to Enum
            mode_str = backup_sched.get('schedule_mode', 'off')
            restore_mode = ScheduleMode.DAILY if mode_str == 'daily' else ScheduleMode.ONCE

            logger.info(f"♻️ Restoring: Resetting schedule to {restore_mode.name} at {backup_sched['schedule_time']}")

            await self.set_schedule(
                mode=restore_mode,
                hour=backup_sched['schedule_hour'],
                minute=backup_sched['schedule_minute'],
                temp_celsius=backup_sched['schedule_temperature']
            )
        else:
            # If schedule was originally off, ensure it stays off
            logger.info("♻️ Restoring: Disabling schedule (as it was originally off)")
            await self.set_schedule(mode=ScheduleMode.OFF)

        logger.info("✅ Done: Kettle is ON and schedule is restored.")
