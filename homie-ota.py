#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__    = 'Jan-Piet Mens <jpmens()gmail.com> & Ben Jones'
__copyright__ = 'Copyright 2016 Jan-Piet Mens'

# wget http://bottlepy.org/bottle.py
# ... or ... pip install bottle
from bottle import auth_basic, get, post, route, request, run, static_file, HTTPResponse, template, abort, view, redirect
import paho.mqtt.client as paho   # pip install paho-mqtt
import bottlesession as bs
import os
import signal
import sys
import hashlib
import logging
import atexit
from persist import PersistentDict
import json
import fileinput
import time
import re
import base64

try:
    import ConfigParser as configparser
except ImportError:
    import configparser

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

# Script name (without extension) used for config/logfile names
APPNAME = os.path.splitext(os.path.basename(__file__))[0]
INIFILE = os.getenv('INIFILE', APPNAME + '.ini')
LOGFILE = os.getenv('LOGFILE', APPNAME + '.log')

# max length that Homie will accept when publishing to $ota
OTA_HOMIE_PAYLOAD_MAX_LENGTH = 16

# Read the config file
if not os.path.exists(INIFILE):
    logging.error("Cannot open ini file %s." % (INIFILE))
    sys.exit(2)
config = configparser.RawConfigParser()
config.read(INIFILE)

# Use ConfigParser to pick out the settings
DEBUG = config.getboolean("global", "DEBUG")
try:
    DEBUG_SENSOR = config.getboolean("global", "DEBUG_SENSOR")
except:
    DEBUG_SENSOR = True
OTA_HOST = config.get("global", "OTA_HOST")
OTA_PORT = config.getint("global", "OTA_PORT")
OTA_ENDPOINT = config.get("global", "OTA_ENDPOINT")
OTA_FIRMWARE_ROOT = config.get("global", "OTA_FIRMWARE_ROOT")
OTA_BASE_URL = ""
try:
    OTA_BASE_URL = config.get("global", "OTA_BASE_URL")
except:
    pass
OTA_FIRMWARE_BASE64 = True
try:
    OTA_FIRMWARE_BASE64 = config.getboolean("global", "OTA_FIRMWARE_BASE64")
except:
    pass
try:
    HTTP_USER = config.get("global","HTTP_USER")
except:
    pass
try:
    HTTP_PASSWORD = config.get("global","HTTP_PASSWORD")
except:
    pass
MQTT_HOST = config.get("mqtt", "MQTT_HOST")
MQTT_PORT = config.getint("mqtt", "MQTT_PORT")
MQTT_USERNAME = None
MQTT_PASSWORD = None
MQTT_CAFILE = None
try:
    MQTT_USERNAME = config.get("mqtt", "MQTT_USERNAME")
except:
    pass
try:
    MQTT_PASSWORD = config.get("mqtt", "MQTT_PASSWORD")
except:
    pass
try:
    MQTT_CAFILE = config.get("mqtt", "MQTT_CAFILE")
except:
    pass
MQTT_SENSOR_PREFIX = config.get("mqtt", "MQTT_SENSOR_PREFIX")


# Initialise logging
LOGFORMAT = '%(asctime)-15s %(levelname)-5s %(message)s'

if DEBUG:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.DEBUG,
                        format=LOGFORMAT)
else:
    logging.basicConfig(filename=LOGFILE,
                        level=logging.INFO,
                        format=LOGFORMAT)

try:
    if(config.get("mqtt", "MQTT_USERNAME")):
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
        console.setFormatter(formatter)
        logging.getLogger('').addHandler(console)
except:
    pass

logging.info("Starting " + APPNAME)
logging.info("INFO MODE")
logging.debug("DEBUG MODE")
logging.debug("INIFILE = %s" % INIFILE)

# MQTT client
mqttc = paho.Client("%s-%d" % (APPNAME, os.getpid()), clean_session=True, userdata=None, protocol=paho.MQTTv311)

# Persisted inventory store
db = PersistentDict(os.path.join(OTA_FIRMWARE_ROOT, 'inventory.json'), 'c', format='json')
sensors = PersistentDict(os.path.join(OTA_FIRMWARE_ROOT, 'sensors.json'), 'c', format='json')

# Initialize bottlesession
session_manager = bs.CookieSession()
valid_user = bs.authenticator(session_manager, login_url='/login')

@get('/login')
@view('static/login.html')
def login():
   session = session_manager.get_session()
   if session['valid']:
       redirect('/')

@post('/login')
@view('static/login.html')
def doLogin():
   session = session_manager.get_session()
   username = request.forms.get('username')
   password = request.forms.get('password')
   if not username or not password:
      return redirect('/')
   session['valid'] = False
   if username==HTTP_USER and password==HTTP_PASSWORD:
      session['valid'] = True
   session_manager.save(session)
   if not session['valid']:
      return { 'error' : 'Username or password is invalid' }
   redirect(request.get_cookie('validuserloginredirect', '/'))

@route('/logout')
def logout():
   session = session_manager.get_session()
   session['valid'] = False
   session_manager.save(session)
   redirect('/login')

def check(user, pw):
    # Check user/pw here and return True/False
    if  user == HTTP_USER and pw == HTTP_PASSWORD:
        return True
    else:
        return False

def conditional_decorator(condition, decorator):
    return decorator if condition else lambda x: x

def generate_ota_payload(firmware):
    # if no '@' then payload is just a version number
    if '@' not in firmware:
        return firmware

    fw_name, fw_version = firmware.split('@')
    hash = hashlib.sha1()
    hash.update(fw_name)

    # ensure our hash doesn't make our payload too big
    fw_hashlen = OTA_HOMIE_PAYLOAD_MAX_LENGTH - len(fw_version) - 1
    fw_hash = hash.hexdigest()[:fw_hashlen]

    # ota payload is <hash>@<version>
    return "%s@%s" % (fw_hash, fw_version)

def handleterm(signum, frame):
    logging.info("SIGTERM received")
    sys.exit(0)

def exitus():
    db.sync()
    db.close()
    sensors.sync()
    sensors.close()
    logging.info("CIAO")

def uptime(seconds=0):
    MINUTE = 60
    HOUR = MINUTE * 60
    DAY = HOUR * 24

    seconds = int(seconds)

    days    = int( seconds / DAY )
    hours   = int( ( seconds % DAY ) / HOUR )
    minutes = int( ( seconds % HOUR ) / MINUTE )
    seconds = int( seconds % MINUTE )

    string = ""
    if days > 0:
        string += str(days) + " " + (days == 1 and "day" or "days" ) + ", "

    string = string + "%d:%02d:%02d" % (hours, minutes, seconds)

    return string


@get('/blurb')
@valid_user()
def blurb():
    text =  """Homie OTA server running.
    OTA endpoint is: http://{host}:{port}/{endpoint}
    Firmware root is {fwroot}\n""".format(host=OTA_HOST,
            port=OTA_PORT, endpoint=OTA_ENDPOINT, fwroot=OTA_FIRMWARE_ROOT)

    for root, dirs, files in os.walk(OTA_FIRMWARE_ROOT):
        path = root.split('/')
        text = text + "\t%s %s\n" % ((len(path) - 1) * '--', os.path.basename(root))
        for file in files:
            if file[0] == '.':
                continue
            text = text + "\t\t%s %s\n" % (len(path) * '---', file)

    return text

@get('/firmware')
@valid_user()
def firmware():
    fw = scan_firmware()
    return template('templates/firmware', base_url=OTA_BASE_URL, fw=fw)

@get('/')
@valid_user()
def inventory():
    fw = scan_firmware()
    return template('templates/inventory', base_url=OTA_BASE_URL, db=db, fw=fw)

@get('/<filename:re:.*\.css>')
@valid_user()
def stylesheets(filename):
    return static_file(filename, root='static/css')

@get('/<filename:re:.*\.png>')
@valid_user()
def png(filename):
    return static_file(filename, root='static/img')

@get('/<filename:re:.*\.js>')
@valid_user()
def javascript(filename):
    return static_file(filename, root='static/js')

@get('/log')
@valid_user()
def showlog():
    logdata = open(LOGFILE, "r").read()
    return template('templates/log', base_url=OTA_BASE_URL, data=logdata)

@get('/device/<device>')
@valid_user()
def showdevice(device):

    data = None
    sensor = {}
    if device in db:
        data = db[device]

    if device in sensors:
        sensor = sensors[device]

    return template('templates/device', base_url=OTA_BASE_URL, device=device, data=data, sensor=sensor)

@route('/firmware/<fw_file>', method='DELETE')
@valid_user()
def delete(fw_file):
    fw_path = os.path.join(OTA_FIRMWARE_ROOT, fw_file)

    if not os.path.exists(fw_path):
        resp = "Unable to delete firmware %s, does not exist" % (fw_path)
        logging.warn(resp)

        abort(404, resp)
        return resp

    filename, file_ext = os.path.splitext(fw_file)
    description_file = filename + '.txt'
    description_path = os.path.join(OTA_FIRMWARE_ROOT, description_file)

    if os.path.exists(description_path):
        os.remove(description_path)

    os.remove(fw_path)

    resp = "Deleted firmware %s" % (fw_file)
    logging.info(resp)
    return resp

@route('/upload', method='POST')
@valid_user()
def upload():
    '''Accept an uploaded, compiled binary sketch and obtain the firmware's
       name and version from the magic described in
       https://github.com/jpmens/homie-ota/issues/1
       Store the binary firmware into a corresponding subdirectory in firmwares/
       '''

    upload = request.files.upload
    description = request.forms.get('description')

    if upload and upload.file:
        firmware_binary = upload.file.read()
        filename = upload.filename

        regex_name = re.compile(b"\xbf\x84\xe4\x13\x54(.+)\x93\x44\x6b\xa7\x75")
        regex_version = re.compile(b"\x6a\x3f\x3e\x0e\xe1(.+)\xb0\x30\x48\xd4\x1a")

        regex_name_result = regex_name.search(firmware_binary)
        regex_version_result = regex_version.search(firmware_binary)

        if not regex_name_result or not regex_version_result:
            resp = "No valid firmware in %s" % filename
            logging.info(resp)
            return resp

        fwname = regex_name_result.group(1)
        fwversion = regex_version_result.group(1)
        fw_file = os.path.join(OTA_FIRMWARE_ROOT, fwname + '-' + fwversion + '.bin')
        description_file = os.path.join(OTA_FIRMWARE_ROOT, fwname + '-' + fwversion + '.txt')

        try:
            f = open(fw_file, "wb")
            f.write(firmware_binary)
            f.close()
        except Exception as e:
            resp = "Cannot write %s: %s" % (fw_file, str(e))
            logging.info(resp)
            return resp

        try:
            f = open(description_file, "wb")
            f.write(description)
            f.close()
        except Exception as e:
            resp = "Cannot write description to file %s: %s" % (description_file, str(e))
            logging.info(resp)
            return resp

        resp = "Firmware from %s uploaded as %s" % (filename, fw_file)
        logging.info(resp)
        return resp

    return "File is missing"

@route('/update', method='POST')
@valid_user()
def update():
    device = request.forms.get('device')
    firmware = request.forms.get('firmware')

    if device == '-':
        logging.error("OTA request is aborted due to no device chosen")
        return "OTA request aborted; no device chosen"
    if firmware == '-':
        logging.error("OTA request is aborted due to no firmware chosen")
        return "OTA request aborted; no firmware chosen"

    # we are dealing with a homie 2.0 device
    if not device in db :
        info = "Unable to find {} in device list".format(device)
        logging.error(info)
    elif 'homie' in db[device]:
        logging.debug("Homie 2.0 device")
        try:
            (fwname, fwversion) = firmware.split('@')
            logging.debug("Firmware Name: {}, Firmware Version: {}".format(fwname, fwversion))
            for fwdata in scan_firmware().values():
                if fwname == fwdata['firmware'] and fwversion == fwdata['version']:
                    fwread = open("%s/%s" % (OTA_FIRMWARE_ROOT, fwdata['filename']), "r").read()
                    if OTA_FIRMWARE_BASE64:
                        fwpublish = base64.b64encode(fwread)
                    else:
                        fwpublish = bytearray(fwread)
                    m = hashlib.md5()
                    m.update(fwread)
                    fwchecksum = m.hexdigest()
                    topic = "%s/%s/$implementation/ota/firmware/%s" % (MQTT_SENSOR_PREFIX, device, fwchecksum)
                    mqttc.publish(topic, payload=fwpublish, qos=1, retain=False)
                    logging.debug("Firware checksum: {}".format(fwchecksum))
                    info = "OTA request sent to device %s for update to %s (OTA version: 2.0)" % (device, firmware)
                    logging.info(info)
                    break
            else:
                info = "Unable to find the firmware in folder"
                logging.error(info)
        except Exception as e:
            info = str(e)
            logging.error("Generic error: {}".format(str(e)))
    else:
        logging.debug("Homie 1.5 device")
        topic = "%s/%s/$ota" % (MQTT_SENSOR_PREFIX, device)
        payload = generate_ota_payload(firmware)
        mqttc.publish(topic, payload=payload, qos=1, retain=False)
        info = "OTA request sent to device %s for update to %s (OTA version: 1.5)" % (device, firmware)
        logging.info(info)
    return info

# Handle deleting a device from the mqtt broker, and the local db.
@route('/device/<device_id>', method='DELETE')
@valid_user()
def delete_device(device_id):
    topics = "%s/%s/#" % (MQTT_SENSOR_PREFIX, device_id)
    mqttc.loop_stop()
    mqttc.subscribe(topics, 0)
    mqttc.message_callback_add(topics, on_delete_message)
    mqttc.loop_start()
    logging.info("Starting delete of topics for device %s" % (device_id))

    # Give the callback time before returning
    time.sleep(2)

    mqttc.loop_stop()
    mqttc.message_callback_remove(topics)
    mqttc.unsubscribe(topics)
    mqttc.loop_start()
    info = "Deleted topics for %s" % (device_id)
    logging.info(info)
    del db[device_id]
    del sensors[device_id]

    return info

def scan_firmware():
    fw = {}
    for fw_file in os.listdir(OTA_FIRMWARE_ROOT):
        fw_path = os.path.join(OTA_FIRMWARE_ROOT, fw_file)
        if not os.path.isfile(fw_path):
            continue
        if not fw_file.endswith('.bin'):
            continue

        regex = re.compile("(.*)\-((\d+\.\d+\.\d+\.\d+)|(\d+\.\d+.\d+))\.bin")
        regex_result = regex.search(fw_file)

        if not regex_result:
            logging.debug("Could not parse firmware details from %s, skipping" % (fw_file))
            continue

        fw[fw_file] = {}
        fw[fw_file]['filename'] = fw_file
        firmware = regex_result.group(1)
        version = regex_result.group(2)
        fw[fw_file]['firmware'] = firmware
        fw[fw_file]['version'] = version

        description = ""
        try:
            description = open("%s/%s-%s.txt" % (OTA_FIRMWARE_ROOT, firmware, version), "r").read()
        except:
            pass
        fw[fw_file]['description'] = description


        stat = os.stat(fw_path)
        fw[fw_file]['size'] = stat.st_size

    #print json.dumps(fw, indent=4)
    return fw


# header X-Esp8266-Ap-Mac = 1A:FE:34:D4:06:55
# header X-Esp8266-Sketch-Size = 367776
# header X-Esp8266-Sta-Mac = 18:FE:34:D4:06:55
# header X-Esp8266-Free-Space = 679936
# header X-Esp8266-Chip-Size = 4194304
# header X-Esp8266-Mode = sketch
# header Content-Length =
# header X-Esp8266-Sdk-Version = 1.5.3(aec24ac9)
# header Host = 192.168.1.130:9080
# header Connection = close
# header User-Agent = ESP8266-http-Update
# header X-Esp8266-Version = d40655e0=button-homie@1.0.0->a75ebc7c7f@1.0.1
# header Content-Type = text/plain

@get(OTA_ENDPOINT)
def ota():

    headers = request.headers
    for k in headers:
        logging.debug("header " + k + ' = ' + headers[k])

    try:
        if '->' in headers.get('X-Esp8266-Version', None):
            # X-Esp8266-Version = d40655e0=button-homie@1.0.0->a75ebc7c7f@1.0.1
            device, f = headers.get('X-Esp8266-Version', None).split('=')
            firmware_name, have_version, want_version = f.split('@')
        else:
            # X-Esp8266-Version = cf3a07e0=h-sensor=1.0.1=1.0.2
            device, firmware_name, have_version, want_version = headers.get('X-Esp8266-Version', None).split('=')
    except:
        raise
        logging.warn("Can't find X-Esp8266-Version in headers; returning 403")
        return HTTPResponse(status=403, body="Not permitted")

    # Record additional detains in DB
    if device not in db:
        db[device] = {}
    db[device]['mac']           = headers.get('X-Esp8266-Ap-Mac', None)
    db[device]['free_space']    = headers.get('X-Esp8266-Free-Space', None)
    db[device]['chip_size']     = headers.get('X-Esp8266-Chip-Size', None)
    db[device]['sketch_size']   = headers.get('X-Esp8266-Sketch-Size', None)

    logging.info("Homie firmware=%s, have=%s, want=%s on device=%s" % (firmware_name, have_version, want_version, device))

    # if the want_version contains the special '@' separator then
    # this is a request from ourselves with both fw_name and
    # fw_version included - allowing for fw changes
    fw_file = None
    if '@' in want_version:
        fw = scan_firmware()
        for fw_key in fw:
            firmware = "%s@%s" % (fw[fw_key]['firmware'], fw[fw_key]['version'])
            if generate_ota_payload(firmware) == want_version:
                fw_file = fw[fw_key]['filename']
                break
    else:
        fw_name = firmware_name
        fw_version = want_version
        fw_file = "%s-%s.bin" % (fw_name, fw_version)

    if fw_file is None:
        logging.warn("Firmware not found, %s does not match any firmware in our list; returning 304" % (want_version))
        return HTTPResponse(status=304, body="OTA aborted, firmware not found")

    fw_path = os.path.join(OTA_FIRMWARE_ROOT, fw_file)
    if not os.path.exists(fw_path):
        logging.warn("%s not found; returning 304" % (fw_path))
        return HTTPResponse(status=304, body="OTA aborted, firmware not found")

    # check free space vs .bin file on disk and refuse
    stat = os.stat(fw_path)
    fw_size = stat.st_size
    try:
        free_space = headers.get('X-Esp8266-Free-Space', None)
        if free_space and free_space < fw_size:
            logging.warn("Firmware too big, %d free on device but binary is %d; returning 304" % (free_space, fw_size))
            return HTTPResponse(status=304, body="OTA aborted, not enough free space on device")
    except:
        logging.warn("Can't find X-Esp8266-Free-Space in headers; skipping size checks")

    logging.info("Returning OTA firmware %s" % (fw_path))
    return static_file(fw_file, root=OTA_FIRMWARE_ROOT)


def on_connect(mosq, userdata, flags, rc):
    mqttc.subscribe("%s/+/+" % (MQTT_SENSOR_PREFIX), 0)
    mqttc.subscribe("%s/+/+/+" % (MQTT_SENSOR_PREFIX), 0)
    mqttc.subscribe("%s/+/$implementation/ota/#" % (MQTT_SENSOR_PREFIX), 0)

# on_delete_message handles deleting the topic the messages was received on.
def on_delete_message(mosq, userdata, msg):
    try:
        msg.payload = msg.payload.decode('utf-8')
    except:
        logging.debug("Unable to decode this payload: {}".format(msg.payload))
    logging.debug("Received delete callback for topic '%s'" % msg.topic)
    if len(msg.payload) == 0:
        return
    # Publish a retain message of zero bytes.
    mqttc.publish(msg.topic, payload='', qos=1, retain=True)

def on_sensor(mosq, userdata, msg):
    try:
        msg.payload = msg.payload.decode('utf-8')
    except:
        logging.debug("Unable to decode this payload: {}".format(msg.payload))
    if msg.topic.endswith("$ota/payload"):
        logging.info("Received OTA payload from %s" % msg.topic)
        return
    elif msg.topic.endswith("$fw/name") or msg.topic.endswith("$fw/version"):
        logging.debug("FW message %s %s" % (msg.topic, str(msg.payload)))
    elif DEBUG_SENSOR:
        logging.debug("SENSOR %s %s" % (msg.topic, str(msg.payload)))

    try:
        t = str(msg.topic)
        t = t[len(MQTT_SENSOR_PREFIX) + 1:]      # remove MQTT_SENSOR_PREFIX/ from begining of topic
        device, key, subkey = t.split('/')

        if key == "$fw":
            if subkey == "name":
                db[device]["fwname"] = str(msg.payload)
            if subkey == "version":
                db[device]["fwversion"] = str(msg.payload)
            return

        # Version of the Homie convention the device conforms to
        if key == "$homie":
            db[device]["homie"] = str(msg.payload)

        subtopic = "%s/%s" % (key, subkey)
        # print "DATA", device, subtopic, msg.payload

        # Homie 2.0 uptime
        if (subtopic == "$uptime/value") or (subtopic == "$stats/uptime"):
            db[device]["human_uptime"] = uptime(msg.payload)
            return

        if key == "$stats":
            if subkey == "signal":
                db[device]["signal"] = str(msg.payload)
            return

        if device not in sensors:
            sensors[device] = {}
        sensors[device][subtopic] = msg.payload
    except Exception as e:
        logging.error("Cannot extract sensor device/data: for %s: %s" % (str(msg.topic), str(e)))

def on_ota_info(mosq, userdata, msg):
    device = msg.topic.split('/')[1]
    progress = re.compile("206\s(?P<current>[0-9]+)\/(?P<all>[0-9]+)")
    reason = re.compile("[0-9]+\s(?P<reason>.*)")
    try:
        msg.payload = msg.payload.decode('utf-8')
    except:
        logging.debug("Unable to decode this payload: {}".format(msg.payload))
    if msg.topic.endswith('status'):
        if msg.payload == "200":
            logging.info("{}: Flash has been done correctly".format(device))
        elif msg.payload == "202":
            logging.info("{}: OTA request/checksum has been accepted".format(device))
        elif msg.payload == "304":
            logging.info("{}: The current firmware is already up-to-date".format(device))
        elif msg.payload == "403":
            logging.warning("{}: OTA is not enabled".format(device))
        elif msg.payload.startswith("206"):
            if DEBUG:
                data = progress.match(msg.payload)
                logging.debug("{}: OTA Flashing: {}/{}".format(device, data.group('current'), data.group('all')))
        elif msg.payload.startswith("400"):
            data = reason.match(msg.payload)
            logging.error("{}: OTA is aborted due to error on server: {}".format(device, data.group('reason')))
        elif msg.payload.startswith("500"):
            data = reason.match(msg.payload)
            logging.error("{}: OTA is aborted due to error on client: {}".format(device, data.group('reason')))
        else:
            logging.info("{}: Unknown status: {}".format(device, msg.payload))



def on_control(mosq, userdata, msg):
    try:
        msg.payload = msg.payload.decode('utf-8')
    except:
        logging.debug("Unable to decode this payload: {}".format(msg.payload))
    logging.debug("CONTROL %s %s" % (msg.topic, str(msg.payload)))

    try:
        t = str(msg.topic)
        t = t[len(MQTT_SENSOR_PREFIX) + 1:]      # remove MQTT_SENSOR_PREFIX/ from begining of topic

        device, key = t.split('/')
        if key.startswith('$'):                 # if key starts with '$'
            key = key[1:]                       # remove '$'

        if device not in db:
            db[device] = {}
        db[device][key] = str(msg.payload)

        if key == 'uptime':
            db[device]['human_uptime'] = uptime( db[device].get('uptime', 0) )
    except Exception as e:
        logging.error("Cannot extract control device/data: for %s: %s" % (str(msg.topic), str(e)))

def on_disconnect(mosq, userdata, rc):
    reasons = {
       '0' : 'Connection Accepted',
       '1' : 'Connection Refused: unacceptable protocol version',
       '2' : 'Connection Refused: identifier rejected',
       '3' : 'Connection Refused: server unavailable',
       '4' : 'Connection Refused: bad user name or password',
       '5' : 'Connection Refused: not authorized',
    }
    reason = reasons.get(rc, "code=%s" % rc)
    logging.debug("Disconnected: %s", reason)

def on_log(mosq, userdata, level, string):
    logging.debug(string)

if __name__ == '__main__':

    if not os.path.exists(OTA_FIRMWARE_ROOT):
        logging.error("Firmware root (%s) does not exist (or is not a directory)"% (OTA_FIRMWARE_ROOT))
        sys.exit(2)

    mqttc.on_connect = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_message = on_control
    mqttc.message_callback_add("%s/+/+/+" % (MQTT_SENSOR_PREFIX), on_sensor)
    mqttc.message_callback_add("%s/+/$implementation/ota/#" % (MQTT_SENSOR_PREFIX), on_ota_info)
    # mqttc.on_log = on_log

    if MQTT_CAFILE:
        mqttc.tls_set(MQTT_CAFILE)

    if MQTT_USERNAME:
        mqttc.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    logging.debug("Attempting connection to MQTT broker at %s:%d..." % (MQTT_HOST, MQTT_PORT))
    try:
        mqttc.connect(MQTT_HOST, MQTT_PORT, 60)
    except Exception as e:
        logging.error("Cannot connect to MQTT broker at %s:%d: %s" % (MQTT_HOST, MQTT_PORT, str(e)))
        sys.exit(2)

    mqttc.loop_start()

    signal.signal(signal.SIGTERM, handleterm)
    atexit.register(exitus)

    try:
        run(host=OTA_HOST, port=OTA_PORT, debug=DEBUG)
    except KeyboardInterrupt:
        mqttc.loop_stop()
        mqttc.disconnect()
        sys.exit(0)
    except:
        raise
