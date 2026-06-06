# Quick I2C scanner. Run once on the Pico to find the BME280's address.
#
# Usage in Thonny:
#   1. Open this file (File → Open... → firmware/i2c_scan.py).
#   2. Make sure the interpreter is set to MicroPython on the Pico
#      (Run → Configure interpreter…).
#   3. Press F5 to run it on the device. Output appears in the Shell pane.
#
# Expected output: "Found: ['0x76']" (or 0x77 depending on your breakout's SDO).
# If you see an empty list, double-check wiring and pull-ups (most BME280
# breakouts have pull-ups on board; bare chips need 4.7 kΩ to 3V3 on SDA + SCL).

from machine import Pin, I2C

# I2C0 on GP0 (SDA) / GP1 (SCL) — set per the project's confirmed pinout.
i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=100_000)

found = [hex(a) for a in i2c.scan()]
print("Found:", found)
print("BME280 expected at 0x76 (SDO→GND) or 0x77 (SDO→VCC).")
