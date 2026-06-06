# Pico W weather sensor firmware

MicroPython firmware for the Raspberry Pi Pico W + BME280 outdoor weather
node. Publishes temperature / humidity / pressure to MQTT every 30s. This
covers **Milestone 1** of the project plan — getting a real sensor reading
into a Mosquitto broker so the rest of the pipeline has something to chew on.

## Hardware

| BME280 pin | Pico W pin | Notes |
|---|---|---|
| VIN / VCC  | 3V3 OUT (pin 36) | **Never** 5V — the BME280 is 3.3V only. |
| GND        | GND (pin 38)     | Common ground. |
| SDA        | GP0 (pin 1)      | I2C0 SDA. |
| SCL        | GP1 (pin 2)      | I2C0 SCL. |
| SDO        | GND              | Sets I2C address to 0x76. Tie to VCC for 0x77. |
| CSB        | VCC              | Forces I2C mode (the BME280 also supports SPI). |

Most breakouts (Adafruit, SparkFun, generic) have pull-ups on SDA/SCL on
board. If you're working with a bare chip, add 4.7 kΩ pull-ups to 3V3 on
both lines.

## Files on the device

```
firmware/
├── main.py            # boot → WiFi → NTP → MQTT loop. Runs at every boot.
├── bme280.py          # I2C driver with Bosch compensation routines.
├── config.py          # YOUR credentials and broker target. Gitignored.
├── config.example.py  # Template — copy to config.py and fill in.
└── i2c_scan.py        # Optional: prints I2C addresses on the bus. Run once.
```

`config.py` is in the project `.gitignore`. Do not check it in — it has your
WiFi password.

## Provisioning steps (Thonny workflow)

Prerequisites: MicroPython 1.22+ already flashed to the Pico W (confirmed)
and Thonny installed. If you ever need to re-flash, drag the `.uf2` from
[micropython.org/download/RPI_PICO_W](https://micropython.org/download/RPI_PICO_W/)
onto the device while holding BOOTSEL — the drive remounts as `RPI-RP2` then
disappears once the firmware is written.

### 1. Create your config file

`config.py` is the only file you'll hand-edit — it holds your WiFi password
and the broker address.

```powershell
copy firmware\config.example.py firmware\config.py
```

Open the new `firmware\config.py` in Thonny (**File → Open…**, navigate to
the project's `firmware\` folder, pick `config.py`). Fill in:

- **`WIFI_SSID` / `WIFI_PASS`** — your 2.4 GHz network. The Pico W's radio is
  2.4 GHz only; if your router broadcasts a separate 5 GHz SSID, you must
  use the 2.4 GHz one (often suffixed `-2G` or `-2.4`).
- **`MQTT_HOST`** — the **LAN IP** of the Windows box running Mosquitto, not
  `localhost` or `127.0.0.1` (those point at the Pico itself, not your PC).
  Find it in PowerShell:
  ```powershell
  ipconfig | Select-String "IPv4"
  ```
  Pick the address for your active WiFi/Ethernet adapter — typically
  something like `192.168.1.42`. Avoid `169.254.x.x` (that's link-local,
  meaning Windows couldn't reach DHCP).
- Leave `BME280_ADDR = 0x76` for now; you'll confirm it in step 3.

**Save with Ctrl+S.** Thonny will ask *"Where to save?"* the first time —
choose **This computer**, not Raspberry Pi Pico. We're editing the file on
the PC; the upload to the device happens in step 4.

### 2. Point Thonny at the Pico

1. Plug the Pico W into USB if it isn't already.
2. In Thonny: **Run → Configure interpreter…** (or **Tools → Options →
   Interpreter** depending on Thonny version).
3. Set **Interpreter** to **MicroPython (Raspberry Pi Pico)**. On newer
   Thonny builds it may be listed as **MicroPython (RP2040)** — either works.
4. Set **Port** to the COM port your Pico shows up on (Thonny will usually
   list it as something like `Board CDC @ COMx` or `USB Serial Device
   (COMx)`). If nothing shows up, unplug/replug the Pico and click the
   port dropdown again.
5. Click **OK**. The Shell pane at the bottom should print the MicroPython
   banner:
   ```
   MicroPython v1.22.x on 2024-xx-xx; Raspberry Pi Pico W with RP2040
   Type "help()" for more information.
   >>>
   ```
   If you get *"Couldn't find the device automatically"* or *"Couldn't open
   serial port"*, another program is holding the port. Close any other
   terminal / mpremote / PuTTY session and click the **Stop/Restart backend**
   button (red square in the toolbar) to retry.
6. Turn on the file panes: **View → Files**. Two panes appear on the left —
   **This computer** (top) and **Raspberry Pi Pico** (bottom). Navigate the
   top pane to your project's `firmware\` folder so the four files are
   visible.

### 3. Confirm the BME280's I2C address

In Thonny's top file pane, **double-click `i2c_scan.py`** to open it in the
editor. Press **F5** (or click the green **Run current script** button).
The script runs *on the Pico* (not on your PC) and prints to the Shell:

```
Found: ['0x76']
BME280 expected at 0x76 (SDO→GND) or 0x77 (SDO→VCC).
```

- **`['0x76']`** → leave `config.py` alone, you're set.
- **`['0x77']`** → open `config.py`, change `BME280_ADDR = 0x76` to
  `BME280_ADDR = 0x77`, save again (still on **This computer**).
- **`[]` (empty list)** → wiring problem. Power off the Pico, double-check
  every BME280 pin against the table above, especially that VIN is on 3V3
  (not 5V — that will damage the chip) and that SDO is tied to a rail
  (GND or VCC, not floating). Then re-run the scan.
- **Multiple addresses** → fine, as long as one of them is 0x76 or 0x77.
  The other devices are unrelated.

### 4. Upload the three firmware files to the Pico

In the **This computer** file pane, with the project's `firmware\` folder
open:

1. Right-click **`bme280.py`** → **Upload to /** . You'll see it appear in
   the **Raspberry Pi Pico** pane underneath.
2. Right-click **`config.py`** → **Upload to /**.
3. Right-click **`main.py`** → **Upload to /**.

Order doesn't matter — but all three must be on the device. The
**Raspberry Pi Pico** pane should now show at least:

```
bme280.py
config.py
main.py
```

Do **not** upload `config.example.py` or `i2c_scan.py` — they're not needed
on the device and just take up flash space. Do **not** upload `README.md`.

> **Note:** these files now live on the Pico's flash and survive power
> cycles. To change WiFi credentials later, edit `config.py` on the PC and
> re-upload it (Thonny will ask to overwrite — yes).

### 5a. Install the `umqtt.simple` package onto the Pico (one-time)

`umqtt.simple` used to ship in the Pico W's MicroPython UF2 but was moved
out to `micropython-lib` starting around v1.20, so newer builds (including
v1.28.x) don't include it. Without this step, the first boot fails with
`ImportError: no module named 'umqtt'` in `main.py` line 25.

1. With the Pico still selected as the active interpreter and the Shell
   showing `>>>`, open **Tools → Manage packages…**
2. In the search box, type **`micropython-umqtt.simple`** and press Enter.
3. Click the result, then click **Install**. Thonny downloads the package
   on your PC and copies it to the Pico's flash (you'll see a brief
   progress dialog). When it's done, close the package manager.
4. Quick sanity check at the `>>>` prompt:
   ```python
   from umqtt.simple import MQTTClient
   ```
   No output = success. If you get another `ImportError`, the install
   didn't land — try again, and if it still fails, fall back to manually
   uploading `umqtt/simple.py` from the
   [micropython-lib repo](https://github.com/micropython/micropython-lib/blob/master/micropython/umqtt.simple/umqtt/simple.py)
   into a `umqtt/` folder on the Pico via the Files pane.

This is a one-time setup per Pico — the package persists in flash across
reboots and re-uploads of your own .py files.

### 5b. Reboot the Pico and watch the live output

`main.py` is the magic filename — MicroPython runs it automatically every
time the board powers up or soft-resets. To kick it off right now:

1. Click in the **Shell** pane (bottom) so it has keyboard focus.
2. Press **Ctrl+D**. This issues a soft reset; the Shell will print
   `MPY: soft reboot` and the boot sequence will start streaming live:
   ```
   --- pico-a1b2c3d4 firmware 0.1.0 booting ---
   WiFi: connecting to MyHomeWiFi...
   WiFi: connected, ip=192.168.1.55, rssi=-58
   NTP: synced, utc=1717610392
   I2C: scan = ['0x76']
   MQTT: connected to 192.168.1.42:1883 as pico-a1b2c3d4
   pub weather/pico-a1b2c3d4/state: {"ts": 1717610400.0, "temperature_c": 21.34, ...}
   ```
3. Every 30 seconds another `pub weather/.../state` line should appear.
   Leave Thonny open — the Shell will keep streaming as long as the Pico
   stays plugged in.
4. To pause and edit code, click the red **Stop** button (or press
   **Ctrl+C** in the Shell). This raises `KeyboardInterrupt` in `main.py`
   and drops you at the `>>>` REPL. Edit files, re-upload changed ones,
   then Ctrl+D again to relaunch.

If you only see the first few lines and then nothing, jump to the
[Troubleshooting](#troubleshooting) section below — the message that
*didn't* come is usually the clue (`WiFi: connecting...` with no
`connected` means WiFi; `MQTT: connected` missing means the broker isn't
reachable).

## Verifying with mosquitto_sub on the dev machine

Mosquitto is installed at `C:\Program Files\mosquitto\`. From a separate
terminal, with Mosquitto running:

```powershell
& "C:\Program Files\mosquitto\mosquitto_sub.exe" -h localhost -t "weather/#" -v
```

You should see lines like:

```
weather/pico-a1b2c3d4/status {"online": true, "ip": "192.168.1.55", "fw": "0.1.0"}
weather/pico-a1b2c3d4/state {"ts": 1717610400.0, "temperature_c": 21.34, "pressure_hpa": 1013.25, "humidity": 54.2, "rssi": -67}
```

If you want to publish a synthetic payload back the other way (e.g. to test
the server before the Pico is online), **always use `-f payload.json`** —
PowerShell strips inner double quotes when passing inline JSON to native
exes, so `-m '{...}'` will produce a payload the server logs as
`Discarding invalid payload`. (Documented in the project CLAUDE.md.)

## Troubleshooting

- **`ImportError: no module named 'umqtt'` on first boot:** the Pico W's
  MicroPython UF2 no longer bundles `umqtt.simple` (unbundled around v1.20).
  Install it once via Thonny's **Tools → Manage packages →
  micropython-umqtt.simple → Install**. Covered in provisioning step 5a.
- **`WiFi: connecting...` hangs / `WiFi connect timed out`:** the Pico W's
  WiFi is 2.4 GHz only. If your router has separate 2.4 / 5 GHz SSIDs, pick
  the 2.4 GHz one. Also re-check the password (case-sensitive, special chars
  may need escaping — see the config.example.py comments).
- **`OSError: -202` or `[Errno 103] ECONNABORTED` on `client.connect()`:**
  TCP connection refused/reset by the broker. Several causes, in order of
  likelihood:
  1. **Mosquitto 2.0+ secure-by-default** — out of the box it binds to
     `127.0.0.1` only and refuses anonymous. Run it with
     `deploy\mosquitto.dev.conf` (opens LAN + anonymous, dev only).
  2. **Windows Firewall blocking inbound 1883** — open with
     `New-NetFirewallRule -DisplayName "Mosquitto MQTT (dev)" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow`
     in an admin PowerShell.
  3. **`MQTT_HOST` set to `localhost` / `127.0.0.1`** — those resolve on
     the *Pico*, not your dev machine. Use the dev machine's LAN IP.
  4. **Old Mosquitto service still bound to port 1883** — `net stop
     mosquitto` before launching the foreground dev instance.
- **`mosquitto_sub` says "actively refused":** you probably gave it the
  Pico's IP (from the WiFi-connected line) instead of the dev machine's.
  The Pico is the publisher; the broker lives on your PC. Use `-h localhost`
  when subscribing from the same Windows box as Mosquitto.
- **`BME280 not found at 0x76`:** run `i2c_scan.py`. If it shows `['0x77']`,
  update `BME280_ADDR` in `config.py`. If the scan is empty, recheck the
  solder joints on SDA/SCL and that SDO is tied to a rail (floating SDO can
  land at random addresses).
- **Time jumps to year 2000:** NTP failed. Sensor still works; the server
  will stamp `received_at` on ingest, so charts won't lie. Re-check that
  your network has outbound UDP/123 (some guest WiFis block it).

## Cadence and lifetime

Default publish interval is 30s (`PUBLISH_INTERVAL_S` in `config.py`). The
firmware uses BME280 forced mode, so the chip sleeps between reads and
self-heating is minimal — important for outdoor placement where you want
accurate ambient temperature, not "case temperature plus a few degrees."

Battery / deep-sleep operation is **out of scope for v1** per the project
plan. The current firmware assumes a continuous 5V supply (USB or a buck
converter from a larger battery pack).
