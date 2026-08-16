# Electrometer DAQ

Live two-channel electrometer acquisition on a Raspberry Pi 5.
Main script: `main.py` (launches `guis/gui_control.py`, which drives the DAQ
via `adc.py`). `fly.py` is a standalone two-channel test/scope script, not
part of the experiment path -- keep its SENSORS config in sync manually if
the hardware setup below changes.

## Hardware
- 2x ADS1115 ADC, INA159 level-shift front end
- Both sensors now share a single I2C bus, /dev/i2c-1 (GPIO 2/3, onboard
  1.8k pull-ups) -- Faraday Ring's ADDR pin was rewired off GND so it no
  longer collides with the Cup's 0x48
  - Faraday Cup  -> 0x48 (ADDR -> GND)
  - Faraday Ring -> 0x49 (ADDR -> VDD) -- first tried 0x4B (ADDR -> SCL)
    but i2cdetect showed nothing at 0x49/0x4A/0x4B, so the ADDR wiring
    itself needs re-checking if 0x49 doesn't show up either
- INA159 reference is a 2.5 V linear regulator -> 1.25 V offset is correct

## History: dual-bus setup (retired)
Previously the Ring sat on a second bus (/dev/i2c-3, GPIO 6/7) because both
ADS1115 were strapped to the same address. That bus had no Pi-side
pull-ups and was the source of frequent I2C dropouts (retries exhausting,
then the affected worker thread dying permanently -- see git history on
fly.py). Also worth remembering if i2c3 is ever revived: on a Pi 5, RP1
ignores `dtoverlay=i2c3,pins_4_5` and always puts i2c3 on GPIO 6/7, and
400 kHz was unreliable there (Errno 121) without added 2.2k-4.7k pull-ups.

## Conversion chain (order matters)
1. bytes -> int16:  raw = (d[0] << 8) | d[1]
2. two's complement: if raw > 32767: raw -= 65536
3. counts -> volts:  v_adc = raw * (4.096 / 32768)   # PGA-dependent
4. undo INA159:      v_in  = 5.0 * (v_adc - 1.25)    # subtract THEN scale

Real range is -6.25 V to +14.2 V, not the +/-7 V the plot y-limits show.
Negative clips at -6.25 (v_adc cannot go below 0).

## Sanity check
Grounded input should read ~10000 counts / 1.25 V at ADC / 0 V out.

## Software
- One worker thread + one SMBus handle per sensor, shared T0 time origin
- 100 Hz polling, ADC converts at 860 SPS (no anti-alias filter -> aliasing risk)
- 5 s rolling deques; PNG of last 5 s saved on clean exit
- blit=False because the x-axis slides

## I2C self-healing (guis/gui_control.py, unattended multi-week runs)
Seen in the wild: after some I2C glitch the ADS1115 silently resets to its
power-on (single-shot) config. Reads keep succeeding -- no exception ever
raised -- but the conversion register is frozen, so every sample comes back
as raw_counts=0, i.e. a clean, unmoving -6.25 V. Since nothing errors, a
naive reconnect-on-exception approach never fires.
`daq_thread` now handles both failure modes: raised I2C errors trigger a
bus close/reopen + re-init with exponential backoff (capped at 30 s), and
the config register is re-sent every time the motor stops at the inductor
sensor (motor_state['running'] True -> False, see location_tracking.py) --
free to do since no usable charge data is expected during that window
anyway. FALLBACK_REINIT_INTERVAL_S (300 s) is just a backstop for the
motor somehow running continuously longer than that without stopping.