# MicroPython BME280 driver (forced mode).
#
# Implements Bosch's compensation formulas from the BME280 datasheet (rev 1.6,
# Sept 2018). Returns SI units directly: temperature in °C, pressure in hPa,
# humidity in %RH. The server stack uses these units as the wire format — do
# not convert to °F / inHg here. Display conversion lives only in the browser.
#
# Tested on Raspberry Pi Pico W + MicroPython 1.22+. Uses forced mode so the
# chip sleeps between reads (lower self-heating, more accurate temperature).

import time
from micropython import const

# Register addresses (datasheet section 5.3)
_REG_ID         = const(0xD0)
_REG_RESET      = const(0xE0)
_REG_CTRL_HUM   = const(0xF2)
_REG_STATUS     = const(0xF3)
_REG_CTRL_MEAS  = const(0xF4)
_REG_CONFIG     = const(0xF5)
_REG_PRESS_MSB  = const(0xF7)  # 8 bytes: press(3) temp(3) hum(2)
_REG_DIG_T1     = const(0x88)  # 24 bytes of temp+pressure calibration
_REG_DIG_H1     = const(0xA1)
_REG_DIG_H2     = const(0xE1)  # 7 bytes of humidity calibration

CHIP_ID_BME280 = 0x60
CHIP_ID_BMP280 = 0x58  # pressure-only sibling; humidity will read as None


class BME280:
    def __init__(self, i2c, address=0x76):
        self.i2c = i2c
        self.addr = address
        chip_id = self._read_u8(_REG_ID)
        if chip_id not in (CHIP_ID_BME280, CHIP_ID_BMP280):
            raise OSError("BME280 not found at 0x{:02x} (chip id 0x{:02x})".format(address, chip_id))
        self._has_humidity = chip_id == CHIP_ID_BME280

        # Soft reset, wait for NVM copy to finish, then read calibration.
        self._write_u8(_REG_RESET, 0xB6)
        time.sleep_ms(10)
        while self._read_u8(_REG_STATUS) & 0x01:
            time.sleep_ms(2)
        self._read_calibration()

        # Oversampling: x1 temp, x4 pressure, x1 humidity, IIR filter off, forced mode.
        # Forced mode = 1 measurement on demand, then sleep. We trigger each read.
        # ctrl_hum must be written before ctrl_meas to take effect (datasheet 5.4.3).
        self._ctrl_hum = 0b001 if self._has_humidity else 0b000     # osrs_h = x1 or skip
        self._ctrl_meas_base = (0b001 << 5) | (0b011 << 2)          # osrs_t=x1, osrs_p=x4
        self._write_u8(_REG_CONFIG, 0x00)                            # t_sb=0, filter=off
        self._write_u8(_REG_CTRL_HUM, self._ctrl_hum)

    # ---- public ---------------------------------------------------------

    def read(self):
        """Trigger a forced measurement and return (temperature_c, pressure_hpa, humidity).

        Humidity is None on BMP280 (no humidity sensor present).
        """
        # Force mode: write ctrl_meas with mode=01. Sensor will measure once then
        # return to sleep. ctrl_hum must already be set.
        self._write_u8(_REG_CTRL_HUM, self._ctrl_hum)
        self._write_u8(_REG_CTRL_MEAS, self._ctrl_meas_base | 0b01)
        # Max measurement time per datasheet 9.1 with our oversampling: ~10 ms.
        # Poll status.measuring (bit 3) to be safe.
        for _ in range(40):
            time.sleep_ms(2)
            if not (self._read_u8(_REG_STATUS) & 0x08):
                break

        raw = self.i2c.readfrom_mem(self.addr, _REG_PRESS_MSB, 8)
        adc_p = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
        adc_t = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
        adc_h = (raw[6] << 8) | raw[7]

        t_fine, temp_c = self._compensate_temperature(adc_t)
        pressure_pa = self._compensate_pressure(adc_p, t_fine)
        humidity = self._compensate_humidity(adc_h, t_fine) if self._has_humidity else None
        return temp_c, pressure_pa / 100.0, humidity  # hPa for pressure

    # ---- compensation (datasheet 4.2.3) ---------------------------------

    def _compensate_temperature(self, adc_t):
        d = self._dig
        var1 = ((((adc_t >> 3) - (d["T1"] << 1))) * d["T2"]) >> 11
        var2 = (((((adc_t >> 4) - d["T1"]) * ((adc_t >> 4) - d["T1"])) >> 12) * d["T3"]) >> 14
        t_fine = var1 + var2
        temp_c = ((t_fine * 5 + 128) >> 8) / 100.0
        return t_fine, temp_c

    def _compensate_pressure(self, adc_p, t_fine):
        d = self._dig
        var1 = t_fine - 128000
        var2 = var1 * var1 * d["P6"]
        var2 = var2 + ((var1 * d["P5"]) << 17)
        var2 = var2 + (d["P4"] << 35)
        var1 = ((var1 * var1 * d["P3"]) >> 8) + ((var1 * d["P2"]) << 12)
        var1 = (((1 << 47) + var1) * d["P1"]) >> 33
        if var1 == 0:
            return 0  # avoid div-by-zero
        p = 1048576 - adc_p
        p = (((p << 31) - var2) * 3125) // var1
        var1 = (d["P9"] * (p >> 13) * (p >> 13)) >> 25
        var2 = (d["P8"] * p) >> 19
        p = ((p + var1 + var2) >> 8) + (d["P7"] << 4)
        return p / 256.0  # Pa

    def _compensate_humidity(self, adc_h, t_fine):
        d = self._dig
        v = t_fine - 76800
        v = (((((adc_h << 14) - (d["H4"] << 20) - (d["H5"] * v)) + 16384) >> 15) *
             (((((((v * d["H6"]) >> 10) * (((v * d["H3"]) >> 11) + 32768)) >> 10) + 2097152) *
               d["H2"] + 8192) >> 14))
        v = v - (((((v >> 15) * (v >> 15)) >> 7) * d["H1"]) >> 4)
        if v < 0:
            v = 0
        if v > 419430400:
            v = 419430400
        return (v >> 12) / 1024.0  # %RH

    # ---- calibration load ----------------------------------------------

    def _read_calibration(self):
        tp = self.i2c.readfrom_mem(self.addr, _REG_DIG_T1, 24)
        d = {
            "T1": _u16(tp, 0),  "T2": _s16(tp, 2),  "T3": _s16(tp, 4),
            "P1": _u16(tp, 6),  "P2": _s16(tp, 8),  "P3": _s16(tp, 10),
            "P4": _s16(tp, 12), "P5": _s16(tp, 14), "P6": _s16(tp, 16),
            "P7": _s16(tp, 18), "P8": _s16(tp, 20), "P9": _s16(tp, 22),
        }
        if self._has_humidity:
            h1 = self._read_u8(_REG_DIG_H1)
            hb = self.i2c.readfrom_mem(self.addr, _REG_DIG_H2, 7)
            d["H1"] = h1
            d["H2"] = _s16(hb, 0)
            d["H3"] = hb[2]
            # H4 and H5 are 12-bit signed values packed into 3 bytes:
            #   H4 = (hb[3] << 4) | (hb[4] & 0x0F)
            #   H5 = (hb[5] << 4) | (hb[4] >> 4)
            d["H4"] = _sign12((hb[3] << 4) | (hb[4] & 0x0F))
            d["H5"] = _sign12((hb[5] << 4) | (hb[4] >> 4))
            d["H6"] = _sign8(hb[6])
        self._dig = d

    # ---- low-level I/O --------------------------------------------------

    def _read_u8(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0]

    def _write_u8(self, reg, val):
        self.i2c.writeto_mem(self.addr, reg, bytes([val & 0xFF]))


# ---- byte unpacking helpers ----------------------------------------------

def _u16(buf, off):
    return buf[off] | (buf[off + 1] << 8)

def _s16(buf, off):
    v = _u16(buf, off)
    return v - 65536 if v & 0x8000 else v

def _sign8(v):
    return v - 256 if v & 0x80 else v

def _sign12(v):
    return v - 4096 if v & 0x800 else v
