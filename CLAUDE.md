# Electrometer DAQ

Live two-channel electrometer acquisition on a Raspberry Pi 5.
Main script: `fly.py`

## Hardware
- 2x ADS1115 ADC, INA159 level-shift front end
- Both ADS1115 have ADDR strapped to GND -> both are 0x48, cannot be readdressed
- Therefore: two separate I2C buses, not two addresses on one bus
  - Faraday Cup  -> /dev/i2c-1 (GPIO 2/3, has onboard 1.8k pull-ups)
  - Faraday Ring -> /dev/i2c-3 (GPIO 6/7)
- INA159 reference is a 2.5 V linear regulator -> 1.25 V offset is correct

## Pi 5 / RP1 gotcha
`dtoverlay=i2c3,pins_4_5` does NOT put i2c3 on GPIO 4/5 on a Pi 5.
RP1 defaults i2c3 to GPIO 6/7 and ignores the pins_4_5 param.
Wiring: SDA3 = GPIO 6 (phys 31), SCL3 = GPIO 7 (phys 26).
Verify with `pinctrl get 6,7` and `i2cdetect -l`.

## Pull-ups
Bus 3 has no Pi-side pull-ups. 400 kHz was unreliable (Errno 121 on
sustained transfers even though i2cdetect probes passed). Running at
the 100 kHz default. If pushing back to 400 kHz, add 2.2k-4.7k to 3V3
on both SDA3 and SCL3.

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