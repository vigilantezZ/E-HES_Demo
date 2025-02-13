import network
import socket
import _thread
import machine
import gc
import time
from machine import Pin, ADC

# UART
from machine import UART

#Bluetooth
import bluetooth, struct, asyncio

#MQTT
import binascii
import ujson
from umqtt.simple import MQTTClient

class Task_Resource:
    def __init__(self):

        print("CONNECT WIFI")
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.wlan.config(pm=self.wlan.PM_NONE)
        self.wlan.config(txpower=18)
        self.wlan.connect("EMI", "Star1313")

        # Wait for the connection
        while not self.wlan.isconnected():
            time.sleep(1)

        print("Connected to Wi-Fi")
        print("IP Address:", self.wlan.ifconfig()[0])
        self.ip_address = self.wlan.ifconfig()[0]

        print("RUNNING WEB SERVER THREAD")

        self.bt_login_state = False
        

        self.x = ADC(Pin(34))
        self.x.atten(ADC.ATTN_11DB)  
        self.y = ADC(Pin(35))
        self.y.atten(ADC.ATTN_11DB) 
        self.data_x = self.x.read()
        self.data_y = self.y.read()

        # Start reading sensor
        _thread.start_new_thread(self.readADC, ())

        # MQTT
        _thread.start_new_thread(self.mqtt_service, ())

        # UART Connection
        _thread.start_new_thread(self.uart_srv, ())

        # Bluetooth
        import aioble

        self._BLE_SERVICE_UUID = bluetooth.UUID('19b10000-e8f2-537e-4f6c-d104768a1214')
        self._BLE_SENSOR_CHAR_UUID = bluetooth.UUID('19b10001-e8f2-537e-4f6c-d104768a1214')
        self._BLE_LED_UUID = bluetooth.UUID('19b10002-e8f2-537e-4f6c-d104768a1214')
        # How frequently to send advertising beacons.
        self._ADV_INTERVAL_MS = 250_000

        # Register GATT server, the service and characteristics
        self.ble_service = aioble.Service(self._BLE_SERVICE_UUID)
        self.sensor_characteristic = aioble.Characteristic(self.ble_service, self._BLE_SENSOR_CHAR_UUID, read=True, notify=True)
        self.led_characteristic = aioble.Characteristic(self.ble_service, self._BLE_LED_UUID, read=True, write=True, notify=True, capture=True)

        # Register service(s)
        aioble.register_services(self.ble_service)

        asyncio.run(self.bluetooth_server())
    
        # Main thread can perform other tasks if needed
        while True:
            gc.collect()
            time.sleep(1)  # Keep the main thread alive
    
    def mqtt_service(self):
        # MQTT Server Parameters
        MQTT_CLIENT_ID = "clientId-UgORFHZ5Qi"
        MQTT_BROKER    = "mqtt-dashboard.com"
        MQTT_USER      = ""
        MQTT_PASSWORD  = ""
        MQTT_TOPIC     = "TESTEST"

        # MQTT Server connection
        print("Connecting to MQTT server... ", end="")
        client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, user=MQTT_USER, password=MQTT_PASSWORD)
        client.connect()
        print("Connected!")

        while True :
            message = ujson.dumps({
                "adc1": self.data_x,
                "adc2": self.data_y,
            })
            # print("Reporting to MQTT topic {}: {}".format(MQTT_TOPIC, message))
            # Send the message
            client.publish(MQTT_TOPIC, message)
            time.sleep(1)

    # Helper to encode the data characteristic UTF-8
    def _encode_data(self, data):
        return str(data).encode('utf-8')

    # Helper to decode the LED characteristic encoding (bytes).
    def _decode_data(self, data):
        try:
            if data is not None:
                # Decode the UTF-8 data
                number = int.from_bytes(data, 'big')
                return number
        except Exception as e:
            # print("Error decoding temperature:", e)
            return None
    
    async def bluetooth_server(self):
        t1 = asyncio.create_task(self.sensor_task())
        t2 = asyncio.create_task(self.peripheral_task())
        t3 = asyncio.create_task(self.wait_for_write())
        await asyncio.gather(t1, t2)
    
    # Serially wait for connections. Don't advertise while a central is connected.
    async def peripheral_task(self):\
        # Bluetooth
        import aioble
        while True:
            try:
                async with await aioble.advertise(
                    self._ADV_INTERVAL_MS,
                    name="ESP32",
                    services=[self._BLE_SERVICE_UUID],
                    ) as connection:
                        # print("Connection from", connection.device)
                        await connection.disconnected()             
            except asyncio.CancelledError:
                # Catch the CancelledError
                # print("Peripheral task cancelled")
                pass
            except Exception as e:
                # print("Error in peripheral_task:", e)
                pass
            finally:
                # Ensure the loop continues to the next iteration
                await asyncio.sleep_ms(100)

    # Get new value and update characteristic
    async def sensor_task(self):
        while True:
            if self.bt_login_state : 
                DATA = {"adc1": self.data_x, "adc2": self.data_y}
                self.sensor_characteristic.write(self._encode_data(DATA), send_update=True)
                # print('New random value written: ', value)
            await asyncio.sleep_ms(1000)

    async def wait_for_write(self):
        while True:
            try:
                connection, data = await self.led_characteristic.written()
                # print(data)
                # print(type)
                if data == b'login' :
                    # print("Login")
                    self.bt_login_state = True
                if data == b'logout' :
                    # print("Logout")
                    self.bt_login_state = False
                if data == b'show_ip' :
                    self.bt_login_state = False
                    self.sensor_characteristic.write(self._encode_data(str(self.ip_address)), send_update=True)

            except asyncio.CancelledError:
                # Catch the CancelledError
                # print("Peripheral task cancelled")
                pass
            except Exception as e:
                # print("Error in peripheral_task:", e)
                pass
            finally:
                # Ensure the loop continues to the next iteration
                await asyncio.sleep_ms(100)

    def readADC(self):
        while True:
            self.data_x = self.x.read()
            self.data_y = self.y.read()
            time.sleep(1)  # Keep the sensor values updated
    
    def uart_srv(self):
        uart = UART(1, baudrate=115200, tx=19, rx=18)
        # print("UART SERVICE")
        while True: 
            uart.write(str(self.data_x) + "-" + str(self.data_y) + "\r\n")
            uart.read(5)
            adc_values = {"adc1": self.data_x, "adc2": self.data_y}
            print(adc_values)
            time.sleep(1)
    

o_Task = Task_Resource()