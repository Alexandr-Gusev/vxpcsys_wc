import os
import json
import argparse
import subprocess
import base64
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import logging
import sys
import requests


###############################################################################
# bot
###############################################################################


def send_message(text, media_fn, media_t):
    url_exts = {
        "photo": "Photo",
        "video": "Video",
        "audio": "Audio",
        "voice": "Voice",
        "gif": "Animation",
        "sticker": "Sticker"
    }
    url_ext = url_exts.get(media_t, "Message")
    url = "https://api.telegram.org/bot{}/send{}".format(cfg["bot"]["token"], url_ext)
    data = {
        "chat_id": cfg["bot"]["chat_id"]
    }
    files = None
    if url_ext == "Message":
        data["text"] = text
    elif url_ext == "Photo":
        data["caption"] = text
        files = {
            "photo": open(media_fn, "rb")
        }
    elif url_ext == "Video":
        data["caption"] = text
        files = {
            "video": open(media_fn, "rb")
        }
    elif url_ext == "Audio":
        data["caption"] = text
        files = {
            "audio": open(media_fn, "rb")
        }
    elif url_ext == "Voice":
        data["caption"] = text
        files = {
            "voice": open(media_fn, "rb")
        }
    elif url_ext == "Animation":
        data["caption"] = text
        files = {
            "animation": open(media_fn, "rb")
        }
    elif url_ext == "Sticker":
        # info message for sticker
        message_url = "https://api.telegram.org/bot{}/sendMessage".format(cfg["bot"]["token"])
        try:
            res = requests.post(message_url, data=dict(data, text=text), timeout=cfg["bot"]["timeout"]).json()
            if not res["ok"]:
                raise RuntimeError(res)
        except Exception as e:
            logging.warning(e)
            return False
        files = {
            "sticker": open(media_fn, "rb")
        }
    try:
        res = requests.post(url, data=data, files=files, timeout=cfg["bot"]["timeout"]).json()
        if not res["ok"]:
            raise RuntimeError(res)
    except Exception as e:
        logging.warning(e)
        return False


###############################################################################
# docker
###############################################################################


def stop_docker():
    p = subprocess.Popen(
        "docker-compose -f main.yml down",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )
    p.wait()


def start_docker():
    p = subprocess.Popen(
        "docker-compose -f main.yml up -d",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )
    p.wait()


###############################################################################
# core
###############################################################################


WD = True

QR_XPATH = ".//canvas[@role='img']"
SIDE_XPATH = ".//div[@id='side']"
APP_XPATH = ".//div[@role='application']"
ROW_XPATH = ".//div[@role='row']"
COUNTER_XPATH = ".//span[@aria-label='Непрочитанные']"
DATA_XPATH = ".//div[contains(@class, 'copyable-text')]"
DOWN_XPATH = ".//div[@aria-label='Прокрутить вниз']"


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(message)s", datefmt="%Y.%m.%d %H:%M:%S")
    logger = logging.getLogger("vxpcsys_wc")
    logger.setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--cfg", default="cfg.json")
    args = parser.parse_args()

    if not os.path.exists(args.cfg):
        raise RuntimeError("can not find %s" % args.cfg)

    with open(args.cfg) as f:
        cfg = json.loads(f.read())

    for k in ["profiles_location", "downloads_location"]:
        d_abs = os.path.abspath(cfg[k])
        if not os.path.exists(d_abs):
            os.makedirs(d_abs)

    options = webdriver.ChromeOptions()
    options.add_argument("--allow-profiles-outside-user-dir")
    options.add_argument("user-data-dir=%s" % (cfg["remote_profiles_location"] if cfg["mode"] == "remote" else os.path.abspath(cfg["profiles_location"])))
    options.add_argument("--profile-directory=%s" % cfg["profile"])
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--log-level=3")
    options.add_argument("--hide-crash-restore-bubble")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-default-apps")
    prefs = {"download.default_directory": (cfg["remote_downloads_location"] if cfg["mode"] == "remote" else os.path.abspath(cfg["downloads_location"]))}
    options.add_experimental_option("prefs", prefs)
    if cfg["mode"] == "remote":
        stop_docker()
        start_docker()
        time.sleep(cfg["docker_warmup"])
        driver = webdriver.Remote("http://localhost:4444/wd/hub", webdriver.DesiredCapabilities.CHROME, options=options)
    elif cfg["mode"] == "portable":
        options.binary_location = os.path.abspath(cfg["chrome_location"])
        if cfg.get("headless"):
            options.add_argument("--headless=new")
        driver = webdriver.Chrome(service=Service(os.path.abspath(cfg["chromedriver_location"])), options=options)
    else:
        if cfg.get("headless"):
            options.add_argument("--headless=new")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_window_size(1280, 1024)

    driver.get("https://web.whatsapp.com/")

    def wait(xpath, node=driver, timeout=300):
        try:
            return WebDriverWait(node, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
        except:
            raise Exception("timeout (xpath = %s)" % xpath)

    def get_img_as_base64(img_node):
        return driver.execute_script("return arguments[0].toDataURL('image/png').substring(21);", img_node)

    def get_chats():
        chats = []
        side_node = driver.find_element(By.XPATH, SIDE_XPATH)
        for chat_node in side_node.find_elements(By.XPATH, ROW_XPATH):
            title, *details = chat_node.text.split("\n")
            details = "\n".join(details)
            try:
                counter = chat_node.find_element(By.XPATH, COUNTER_XPATH).text
            except:
                counter = ""
            chats.append((chat_node, title, details, counter))
        return chats

    def get_messages():
        try:
            down_node = driver.find(By.XPATH, DOWN_XPATH)
            down_node.click()
        except:
            pass
        messages = []
        application_node = driver.find_element(By.XPATH, APP_XPATH)
        for message_node in application_node.find_elements(By.XPATH, ROW_XPATH):
            data_nodes = message_node.find_elements(By.XPATH, DATA_XPATH)
            info = None
            for data_node in data_nodes:
                try:
                    info = data_node.get_attribute("data-pre-plain-text")
                    break
                except:
                    pass
            if info is not None:
                text = data_node.text.replace("\n", " ")
                messages.append(info + text)
        return messages

    def get_chat_messages(target, timeout=5):
        for chat_node, title, details, counter in get_chats():
            if title == target:
                chat_node.click()
                time.sleep(timeout)
                return get_messages()

    def update_messages(timeout=5):
        for chat_node, title, details, counter in get_chats():
            if counter == "" and all_details.get(title) != details:
                messages = all_messages.setdefault(title, [])

                chat_node.click()
                time.sleep(timeout)
                new_messages = get_messages()

                if messages:
                    last_message = messages[-1]
                    shift = 1
                    for message in new_messages:
                        if message == last_message:
                            new_messages = new_messages[shift:]
                            break
                        shift += 1

                for message in new_messages:
                    messages.append(message)
                    send_message("%s: %s" % (title, message), None, None)

                all_details[title] = details

    def enter(timeout=60):
        qr_not_found = True
        t = time.time()
        while True:
            if qr_not_found:
                try:
                    qr_node = driver.find_element(By.XPATH, QR_XPATH)
                    qr_base64 = get_img_as_base64(qr_node)
                    with open("qr.png", "wb") as f:
                        f.write(base64.b64decode(qr_base64))
                    logger.warning("Scan QR-code within %s s" % timeout)
                    qr_not_found = False
                    t = time.time()
                except:
                    pass

            try:
                driver.find_element(By.XPATH, SIDE_XPATH)
                break
            except:
                pass

            if time.time() - t > timeout:
                raise RuntimeError("timeout (enter)")

            time.sleep(5)

    enter()

    time.sleep(cfg["site_warmup"])
    all_details = {}
    all_messages = {}
    for _, title, details, _ in get_chats():
        all_details[title] = details
        all_messages[title] = []

    while True:
        if WD:
            try:
                update_messages()
            except Exception as e:
                logger.warning(e)
        time.sleep(cfg["scan_interval"])

    driver.close()
