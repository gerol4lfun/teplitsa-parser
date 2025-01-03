import json
import time
import random
import logging
import csv
import re
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

########################
# 1. ЛОГИРОВАНИЕ ГОРОДА #
########################
def setup_logging(city_name):
    logger = logging.getLogger(city_name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(f'teplitsa_parser_{city_name}.log', encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    return logger

###############################
# 2. НАСТРОЙКА SELENIUM-DRАЙВ #
###############################
def setup_driver(chromedriver_path=None):
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # уберите, если хотите видеть окно браузера
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    )

    if chromedriver_path:
        driver = webdriver.Chrome(executable_path=chromedriver_path, options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)
    return driver

#################################
# 3. ПРОВЕРКА, НЕ 404 ЛИ СТРАНИЦА #
#################################
def is_page_available(driver, logger):
    try:
        if "404" in driver.title.lower():
            logger.warning("Страница вернула 404 (title).")
            return False
        driver.find_element(By.XPATH, "//h1[contains(text(), '404')]")
        logger.warning("Страница содержит заголовок '404'.")
        return False
    except NoSuchElementException:
        return True

################################
# 4. ЧТЕНИЕ CSV (ФИЛЬТР: Москва и 1 город)
################################
def read_links_from_csv(csv_file, logger):
    """
    Читает CSV, возвращает СТРОКИ ТОЛЬКО для двух городов:
      - Москва
      - Ставрополь (просто пример, меняйте если нужен другой)
    """
    target_cities = {"Москва", "Ставрополь"}  # <-- поменяйте "Ставрополь" на любой другой город
    links = []
    try:
        with open(csv_file, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                city = row["Город"].strip()
                if city not in target_cities:
                    # пропускаем все города кроме "Москва" и "Ставрополь"
                    continue

                name = row["Название"].strip()
                city_code = row["ГородКод"].strip()
                url = row["URL"].strip()

                links.append({
                    "Название": name,
                    "Город": city,
                    "ГородКод": city_code,
                    "URL": url
                })

        logger.info(f"Из CSV прочитано (фильтр) ссылок: {len(links)} (только Москва + 1 город).")
        return links
    except Exception as e:
        logger.error(f"Ошибка при чтении CSV '{csv_file}': {e}")
        return []

################################
# 5. ИЗВЛЕЧЕНИЕ ХАРАКТЕРИСТИК    #
################################
def extract_characteristics(driver, logger):
    characteristics = {}
    valid_keys = {
        "Каркас",
        "Ширина",
        "Высота",
        "Снеговая нагрузка",
        "Горизонтальные стяжки",
        "Комплектация"
    }
    current_key = None
    try:
        try:
            desc_div = driver.find_element(By.CSS_SELECTOR, "div.prod_desc")
        except NoSuchElementException:
            desc_div = driver.find_element(By.CSS_SELECTOR, "div.description")

        html_desc = desc_div.get_attribute("innerHTML")
        soup = BeautifulSoup(html_desc, "html.parser")

        for br in soup.find_all("br"):
            br.replace_with("\n")

        lines = [ln.strip() for ln in soup.get_text(separator="\n").split("\n") if ln.strip()]
        logger.info("Извлечённые строки характеристик:")
        for ln in lines:
            logger.info(f"  - {ln}")

        for line in lines:
            line = re.sub(r'^[-\s]+', '', line)
            match = re.match(r'^(?P<key>[^:]+):\s*(?P<value>.+)$', line)
            if match:
                key = match.group("key").strip()
                val = match.group("value").strip()
                if key in valid_keys:
                    characteristics[key] = val
                    logger.info(f"Извлечена характеристика: {key} = {val}")
                else:
                    logger.warning(f"Неизвестный ключ: {key} => {val}")
                current_key = None
            else:
                if line.startswith(":"):
                    val = line[1:].strip()
                    if current_key and current_key in valid_keys:
                        characteristics[current_key] = val
                        logger.info(f"Извлечена характеристика: {current_key} = {val}")
                    else:
                        logger.warning(f"Строка без ключа: {val}")
                else:
                    if line in valid_keys:
                        current_key = line
                    else:
                        logger.warning(f"Строка не подходит: {line}")
    except NoSuchElementException:
        logger.warning("Не найден блок характеристик (div.prod_desc / div.description).")
    except Exception as e:
        logger.error(f"Ошибка при извлечении характеристик: {e}")

    logger.info(f"Итоговые характеристики: {characteristics}")
    return characteristics

################################
# 6. ИЗВЛЕЧЕНИЕ ЦЕН (включая 4 м)
################################
def extract_prices(driver, logger):
    prices = {}
    try:
        table = driver.find_element(By.CSS_SELECTOR, "table.tb2.adaptive.poly-price")
        rows = table.find_elements(By.TAG_NAME, "tr")
        logger.info(f"Найдена таблица poly-price, строк: {len(rows)}")

        for row_idx, row in enumerate(rows, start=1):
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 3:
                continue

            product_type = cols[0].text.strip()
            for c_idx in range(2, len(cols)):
                cell = cols[c_idx]
                length_label = cell.get_attribute("data-label") or ""
                length_label = length_label.strip()
                price_text = cell.text.strip()

                if not length_label:
                    logger.debug(f"Строка {row_idx}, col {c_idx} без data-label, пропускаем.")
                    continue

                key = f"{product_type} ({length_label})"
                if price_text:
                    prices[key] = price_text
                    logger.info(f"Извлечена цена: {key} = {price_text}")
                else:
                    prices[key] = "Цена отсутствует"
                    logger.warning(f"Нет цены для {key}")
    except NoSuchElementException:
        logger.warning("Таблица .tb2.adaptive.poly-price не найдена.")
    except Exception as e:
        logger.error(f"Ошибка при извлечении цен: {e}")
    return prices

################################
# 7. ИЗВЛЕЧЕНИЕ ДАННЫХ (ОДНА ТЕПЛИЦА)
################################
def extract_teplitsa_data(driver, url, logger, retries=3):
    data = {}
    attempt = 0
    while attempt < retries:
        try:
            logger.info(f"\nПереходим по ссылке: {url}")
            driver.get(url)

            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Закрываем всплывающее окно (если есть)
            try:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".choose-city-popup .accept-city"))
                )
                popup_btn = driver.find_element(By.CSS_SELECTOR, ".choose-city-popup .accept-city")
                popup_btn.click()
                logger.info("Закрыли всплывающее окно выбора города.")
            except TimeoutException:
                logger.info("Окно города не появилось.")
            except NoSuchElementException:
                logger.info("Кнопка закрытия окна не найдена.")

            # 404?
            if not is_page_available(driver, logger):
                logger.warning("Страница 404, пропускаем.")
                return None

            # Название (h1)
            try:
                h1 = driver.find_element(By.XPATH, "//h1")
                data["Название"] = h1.text.strip()
                logger.info(f"Извлечено название: {data['Название']}")
            except NoSuchElementException:
                data["Название"] = "Не указано"
                logger.warning("Не найден h1.")

            # Характеристики
            chars = extract_characteristics(driver, logger)
            if chars:
                data.update(chars)

            # Цены (включая 4 метра)
            prc = extract_prices(driver, logger)
            data["Цены"] = prc

            return data

        except WebDriverException as e:
            logger.error(f"WebDriverException: {e}, попытка #{attempt+1}. Перезапуск.")
            attempt += 1
            driver.quit()
            driver = setup_driver()
            time.sleep(3)
        except Exception as e:
            logger.error(f"Ошибка при извлечении {url}: {e}, попытка #{attempt+1}.")
            attempt += 1
            time.sleep(3)

    logger.error(f"Не удалось извлечь данные после {retries} попыток. URL={url}")
    return None

############################
# 8. ОСНОВНАЯ ФУНКЦИЯ MAIN #
############################
def main():
    # CSV-файл, где хранятся все ссылки
    # Но мы будем фильтровать, оставляя ТОЛЬКО "Москва" и "Ставрополь".
    csv_file = "teplicy_links_final.csv"

    # Укажите, если нужно, путь к chromedriver
    chromedriver_path = None

    # Логи на глобальном уровне
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("Запуск скрипта для парсинга (Москва + 1 город)...")

    driver = setup_driver(chromedriver_path)
    logging.info("WebDriver запущен успешно.")

    logger = logging.getLogger("GLOBAL")
    # 1. Читаем CSV (только для Москвы и Ставрополя)
    filtered_links = read_links_from_csv(csv_file, logger)

    # 2. Сюда будем складывать результаты
    all_data = []

    # 3. Проходим по каждой ссылке
    for link_info in filtered_links:
        city_name = link_info["Город"]
        logger_city = setup_logging(city_name)

        logger_city.info(f"\nНачинаем парсить: {link_info['Название']} (город: {city_name})")

        data = extract_teplitsa_data(driver, link_info["URL"], logger_city)
        if data:
            data["Город"] = city_name
            all_data.append(data)
            logger_city.info(f"Данные извлечены: {link_info['Название']} ({city_name})")
        else:
            logger_city.warning(f"Не удалось извлечь {link_info['Название']} ({city_name}).")

        time.sleep(random.uniform(1, 2))

    # 4. Закрываем драйвер
    driver.quit()
    logging.info("WebDriver закрыт.")

    # 5. Сохраняем результаты в JSON локально
    output_file = "teplicy_msk_stavropol_data.json"  # или любое название
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        logging.info(f"Результаты сохранены в '{output_file}'")
    except Exception as e:
        logging.error(f"Ошибка при сохранении JSON: {e}")

if __name__ == "__main__":
    main()
