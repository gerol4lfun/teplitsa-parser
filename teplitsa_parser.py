import json
import time
import random
import logging
import csv
import re
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
import os

########################
# 1. ЛОГИРОВАНИЕ ГОРОДА #
########################
def setup_logging(city_name):
    """Создаёт и возвращает логгер для каждого города, пишет лог в файл teplitsa_parser_<city_name>.log."""
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
    chrome_options.add_argument("--headless")  # Если хотите видеть окно браузера, закомментируйте
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # Меняем user-agent, чтобы сайт не подумал, что мы бот (опционально)
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
        logger.warning("Заголовок h1 '404' найден на странице.")
        return False
    except NoSuchElementException:
        return True

################################
# 4. ЧТЕНИЕ CSV СО ВСЕМИ ГОРОДАМИ #
################################
def read_links_from_csv(csv_file, logger):
    """
    Читает CSV-файл (teplicy_links_final.csv), где поля:
      Название, Город, ГородКод, URL
    Возвращает список словарей [{Название, Город, ГородКод, URL}, ...].
    """
    links = []
    try:
        with open(csv_file, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                name = row["Название"].strip()
                city = row["Город"].strip()
                city_code = row["ГородКод"].strip()
                url = row["URL"].strip()
                links.append({
                    "Название": name,
                    "Город": city,
                    "ГородКод": city_code,
                    "URL": url
                })
        logger.info(f"Прочитано ссылок из '{csv_file}': {len(links)}")
        return links
    except Exception as e:
        logger.error(f"Ошибка при чтении CSV '{csv_file}': {e}")
        return []

################################
# 5. ИЗВЛЕЧЕНИЕ ХАРАКТЕРИСТИК    #
################################
def extract_characteristics(driver, logger):
    """Парсит div.prod_desc / div.description, строки вида 'Ключ: значение'."""
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
        for line in lines:
            logger.info(f"  - {line}")

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
                    logger.warning(f"Неизвестный ключ: {key} => {val}, пропускаем.")
                current_key = None
            else:
                # возможно строка начинается с ':'
                if line.startswith(":"):
                    val = line[1:].strip()
                    if current_key and current_key in valid_keys:
                        characteristics[current_key] = val
                        logger.info(f"Извлечена характеристика: {current_key} = {val}")
                    else:
                        logger.warning(f"Строка без ключа: {val}, пропускаем.")
                else:
                    if line in valid_keys:
                        current_key = line
                        logger.info(f"Найден ключ: {current_key}")
                    else:
                        logger.warning(f"Строка не соответствует формату: {line}")
    except NoSuchElementException:
        logger.warning("Не найден блок характеристик (div.prod_desc / div.description).")
    except Exception as e:
        logger.error(f"Ошибка при извлечении характеристик: {e}")

    logger.info(f"Итоговые характеристики: {characteristics}")
    return characteristics

################################
# 6. ИЗВЛЕЧЕНИЕ ЦЕН (4 м И ДР.)  #
################################
def extract_prices(driver, logger):
    """
    Ищет таблицу table.tb2.adaptive.poly-price,
    парсит строки (<tr>), начиная со структура:
      td[0] = "Поликарбонат ... 4мм"
      td[1] = "стоимость" (пропускаем)
      td[2..] = ячейки с data-label="4 метра", "6 метров" и т.д.
    """
    prices = {}
    try:
        table = driver.find_element(By.CSS_SELECTOR, "table.tb2.adaptive.poly-price")
        rows = table.find_elements(By.TAG_NAME, "tr")
        logger.info(f"Найдена таблица poly-price, строк: {len(rows)}")

        for row_idx, row in enumerate(rows, start=1):
            cols = row.find_elements(By.TAG_NAME, "td")
            logger.debug(f"Строка {row_idx}, ячеек: {len(cols)}")
            if len(cols) < 3:
                continue

            # Первый столбец => тип поликарбоната, напр. "Поликарбонат Стандарт 4мм"
            product_type = cols[0].text.strip()
            logger.debug(f"Строка {row_idx}, product_type: {product_type}")

            # Начиная с cols[2..], с data-label="4 метра" и т.д.
            for c_idx in range(2, len(cols)):
                cell = cols[c_idx]
                length_label = cell.get_attribute("data-label") or ""
                length_label = length_label.strip()
                price_text = cell.text.strip()

                if not length_label:
                    logger.debug(f"Нет data-label в ячейке c_idx={c_idx}, пропускаем.")
                    continue

                key = f"{product_type} ({length_label})"
                if price_text:
                    prices[key] = price_text
                    logger.info(f"Извлечена цена: {key} = {price_text}")
                else:
                    prices[key] = "Цена отсутствует"
                    logger.warning(f"Цена для {key} отсутствует.")

    except NoSuchElementException:
        logger.warning("Таблица .tb2.adaptive.poly-price не найдена (цены не извлечены).")
    except Exception as e:
        logger.error(f"Ошибка при извлечении цен: {e}")

    return prices

################################
# 7. ИЗВЛЕЧЕНИЕ ДАННЫХ С ОДНОЙ ТЕПЛИЦЫ
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
                logger.info("Кнопка окна выбора города не найдена.")

            # Проверка 404
            if not is_page_available(driver, logger):
                logger.warning(f"Страница {url} не найдена (404).")
                return None

            # Название (h1)
            try:
                h1 = driver.find_element(By.XPATH, "//h1")
                data["Название"] = h1.text.strip()
                logger.info(f"Извлечено название: {data['Название']}")
            except NoSuchElementException:
                data["Название"] = "Не указано"
                logger.warning("Не найден заголовок h1.")

            # Характеристики
            chars = extract_characteristics(driver, logger)
            if chars:
                data.update(chars)

            # Цены (включая 4 м)
            prices = extract_prices(driver, logger)
            data["Цены"] = prices

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

    logger.error(f"Не удалось извлечь данные для {url} после {retries} попыток.")
    return None

############################
# 8. ОСНОВНАЯ ФУНКЦИЯ main #
############################
def main():
    # CSV со всеми теплицами и городами
    csv_file = "teplicy_links_final.csv"  

    # Укажите путь, если chromedriver лежит не в PATH
    chromedriver_path = None

    # Папка, куда хотим сохранить JSON-итог
    output_folder = "/Users/pavelkulcinskij/Desktop/city2"
    # Убедимся, что такая папка существует
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Настройка логирования
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("Запуск скрипта парсинга...")

    driver = setup_driver(chromedriver_path)
    logging.info("WebDriver успешно запущен.")

    logger = logging.getLogger("GLOBAL")

    # 1. Читаем CSV
    all_links = read_links_from_csv(csv_file, logger)
    all_data = []

    # 2. Для каждой строки (теплица + город + URL)
    for link_info in all_links:
        city_name = link_info["Город"]  # Например, "Москва"
        logger_city = setup_logging(city_name)

        logger_city.info(f"\nНачинаем обработку: {link_info['Название']} (город: {city_name})")

        # 3. Извлекаем данные о теплице
        tepl_data = extract_teplitsa_data(driver, link_info["URL"], logger_city)
        if tepl_data:
            tepl_data["Город"] = city_name
            all_data.append(tepl_data)
            logger_city.info(f"Данные для {link_info['Название']} ({city_name}) извлечены.")
        else:
            logger_city.warning(f"Не удалось извлечь данные для {link_info['Название']} ({city_name}).")

        # 4. Задержка от 1 до 2 сек
        time.sleep(random.uniform(1, 2))

    # 5. Закрываем драйвер
    driver.quit()
    logging.info("WebDriver закрыт.")

    # 6. Сохранение итогового JSON в папку /Users/pavelkulcinskij/Desktop/city2
    output_file = os.path.join(output_folder, "teplicy_all_cities_data.json")
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        logging.info(f"Все данные сохранены в '{output_file}'")
    except Exception as e:
        logging.error(f"Ошибка при сохранении JSON: {e}")

if __name__ == "__main__":
    main()
