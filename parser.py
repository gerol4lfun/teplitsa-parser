import json
import requests
import os
import csv
import re
import time
import random
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

###########################
# НАСТРОЙКА SELENIUM DRIVER
###########################
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    )

    driver = webdriver.Chrome(options=chrome_options)
    return driver

###############################
# ПРОВЕРКА: НЕ 404 ЛИ СТРАНИЦА?
###############################
def is_page_available(driver):
    try:
        if "404" in driver.title.lower():
            return False
        driver.find_element(By.XPATH, "//h1[contains(text(), '404')]")
        return False
    except NoSuchElementException:
        return True

###############################
# ЧТЕНИЕ CSV СО ВСЕМИ ГОРОДАМИ
###############################
def read_links_from_csv(csv_file):
    """
    Ожидаем CSV с колонками:
      Название, Город, ГородКод, URL
    Возвращаем список словарей
    """
    links = []
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            links.append({
                "Название": row["Название"].strip(),
                "Город": row["Город"].strip(),
                "ГородКод": row["ГородКод"].strip(),
                "URL": row["URL"].strip()
            })
    return links

###################################
# ИЗВЛЕЧЕНИЕ ХАРАКТЕРИСТИК (ПРИМЕР)
###################################
def extract_characteristics(driver):
    characteristics = {}
    try:
        # Ищем либо div.prod_desc, либо div.description
        try:
            desc_div = driver.find_element(By.CSS_SELECTOR, "div.prod_desc")
        except NoSuchElementException:
            desc_div = driver.find_element(By.CSS_SELECTOR, "div.description")

        html_desc = desc_div.get_attribute("innerHTML")
        soup = BeautifulSoup(html_desc, "html.parser")

        # Заменим <br> на \n
        for br in soup.find_all("br"):
            br.replace_with("\n")

        lines = [ln.strip() for ln in soup.get_text(separator="\n").split("\n") if ln.strip()]

        # Пример: ищем строки вида "Каркас: оцинкованная труба..."
        # Это пример, адаптируйте под реальную верстку
        for line in lines:
            match = re.match(r'([^:]+):\s*(.+)', line)
            if match:
                key = match.group(1).strip()
                val = match.group(2).strip()
                characteristics[key] = val

    except NoSuchElementException:
        pass
    return characteristics

##########################################
# ИЗВЛЕЧЕНИЕ ЦЕН (ПРИМЕР) ВКЛЮЧАЯ 4 МЕТРА
##########################################
def extract_prices(driver):
    prices = {}
    try:
        table = driver.find_element(By.CSS_SELECTOR, "table.tb2.adaptive.poly-price")
        rows = table.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 3:
                continue

            # Например, cols[0] = "Поликарбонат Стандарт 4мм", cols[1]="стоимость", cols[2..]=длины
            product_type = cols[0].text.strip()

            for c_idx in range(2, len(cols)):
                cell = cols[c_idx]
                length_label = cell.get_attribute("data-label") or ""
                length_label = length_label.strip()  # "4 метра"
                price_text = cell.text.strip()       # "16990 руб."

                if length_label:
                    key = f"{product_type} ({length_label})"
                    prices[key] = price_text
    except NoSuchElementException:
        pass
    return prices

#####################################
# СБОР ДАННЫХ С ОДНОЙ СТРАНИЦЫ
#####################################
def parse_one(driver, url):
    data = {}
    driver.get(url)

    # Ждём body
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    # Закрываем всплывающие окна (пример)
    # try:
    #     popup = WebDriverWait(driver, 3).until(
    #         EC.element_to_be_clickable((By.CSS_SELECTOR, ".choose-city-popup .accept-city"))
    #     )
    #     popup.click()
    # except:
    #     pass

    # Проверка 404
    if not is_page_available(driver):
        return None

    # Название
    try:
        h1 = driver.find_element(By.XPATH, "//h1")
        data["Название"] = h1.text.strip()
    except NoSuchElementException:
        data["Название"] = "Не указано"

    # Характеристики
    chars = extract_characteristics(driver)
    data.update(chars)

    # Цены
    prices = extract_prices(driver)
    data["Цены"] = prices

    return data

###################################
# ЗАПИСЬ В SUPABASE (REST API)
###################################
def insert_to_supabase(all_data):
    """Пример вставки через REST API. 
       Нужно в GitHub Secrets прописать SUPABASE_URL и SUPABASE_SERVICE_KEY
    """
    import requests

    SUPABASE_URL = os.environ["SUPABASE_URL"]   # secrets
    SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # secrets
    TABLE_NAME = "prices"  # ваша таблица
    
    endpoint = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        # "Prefer": "resolution=merge-duplicates"  # если нужен upsert
    }

    resp = requests.post(endpoint, headers=headers, json=all_data)
    print("Status:", resp.status_code, "Resp:", resp.text)

############################
# ОСНОВНАЯ ФУНКЦИЯ main
############################
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # 1. Читаем CSV
    csv_file = "teplicy_links_final.csv"  # Убедитесь, что лежит в репо
    links = read_links_from_csv(csv_file)
    logging.info(f"Всего ссылок для парсинга: {len(links)}")

    # 2. Настройка Selenium
    driver = setup_driver()

    # 3. Парсим
    all_data = []
    for ln in links:
        city = ln["Город"]
        url = ln["URL"]
        name = ln["Название"]
        logging.info(f"Парсим: {name} / {city} => {url}")

        one_data = parse_one(driver, url)
        if one_data:
            # Добавим поле Город, если нужно
            one_data["Город"] = city
            all_data.append(one_data)
        else:
            logging.warning(f"Не удалось извлечь данные: {name} / {city}")

        time.sleep(random.uniform(1, 2))

    driver.quit()

    logging.info(f"Парсинг завершён, всего {len(all_data)} записей.")

    # 4. Отправляем в Supabase
    if all_data:
        insert_to_supabase(all_data)
    else:
        logging.warning("all_data пустой, нет данных для записи.")

if __name__ == "__main__":
    main()

