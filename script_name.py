import json
import time
import random
import logging
import csv
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# Настройка логирования для каждого города
def setup_logging(city_name):
    logger = logging.getLogger(city_name)
    logger.setLevel(logging.DEBUG)  # Уровень DEBUG для подробного логирования
    if not logger.handlers:
        fh = logging.FileHandler(f'teplitsa_parser_{city_name}.log', encoding='utf-8')
        fh.setLevel(logging.DEBUG)  # Логируются все сообщения уровня DEBUG и выше
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    return logger

def setup_driver(chromedriver_path=None):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-dev-shm-usage")  # Улучшение стабильности
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)")
    # Добавление прокси, если необходимо
    # chrome_options.add_argument('--proxy-server=http://your-proxy-address:port')

    if chromedriver_path:
        driver = webdriver.Chrome(executable_path=chromedriver_path, options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)
    return driver

def is_page_available(driver, logger):
    try:
        if "404" in driver.title:
            logger.warning("Страница вернула 404 ошибку.")
            return False
        driver.find_element(By.XPATH, "//h1[contains(text(), '404')]")
        logger.warning("Найден заголовок 404.")
        return False
    except NoSuchElementException:
        return True

def read_links_from_csv(csv_file, logger):
    links = []
    try:
        with open(csv_file, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                name = row['Название'].strip()
                city = row['Город'].strip()
                city_code = row['ГородКод'].strip()
                url = row['URL'].strip()
                if name and city and city_code and url:
                    links.append({
                        'Название': name,
                        'Город': city,
                        'ГородКод': city_code,
                        'URL': url
                    })
                    logger.info(f"Найдена ссылка на теплицу: {url} для города: {city}")
                else:
                    logger.warning(f"Неполная информация в строке: {row}")
        logger.info(f"Всего найдено ссылок на теплицы: {len(links)}")
        return links
    except Exception as e:
        logger.error(f"Ошибка при чтении CSV-файла {csv_file}: {e}")
        return links

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

    current_key = None  # Переменная для хранения текущего ключа

    try:
        try:
            desc_div = driver.find_element(By.CSS_SELECTOR, "div.prod_desc")
        except NoSuchElementException:
            desc_div = driver.find_element(By.CSS_SELECTOR, "div.description")

        desc_html = desc_div.get_attribute("innerHTML")

        soup = BeautifulSoup(desc_html, "html.parser")
        # Заменяем <br> на \n для удобства
        for br in soup.find_all("br"):
            br.replace_with("\n")

        desc_text = soup.get_text(separator="\n")
        lines = [line.strip() for line in desc_text.split("\n") if line.strip()]

        logger.info("Извлеченные строки характеристик:")
        for line in lines:
            logger.info(f"  - {line}")

        # Парсинг ключ-значение с использованием регулярных выражений
        for line in lines:
            logger.debug(f"Обрабатываем строку: '{line}'")
            # Удаляем ведущие символы '-' и пробелы
            line = re.sub(r'^[-\s]+', '', line)
            match = re.match(r'^(?P<key>[^:]+):\s*(?P<value>.+)$', line)
            if match:
                key = match.group('key').strip()
                value = match.group('value').strip()
                if key in valid_keys:
                    characteristics[key] = value
                    logger.info(f"Извлечена характеристика: {key} = {value}")
                else:
                    logger.warning(f"Неизвестный ключ: {key}. Пропускаем.")
                current_key = None  # Сброс текущего ключа
            else:
                # Обработка строк без двоеточия, возможно, продолжение предыдущего значения
                if line.startswith(":"):
                    value = line[1:].strip()
                    if current_key and current_key in valid_keys:
                        characteristics[current_key] = value
                        logger.info(f"Извлечена характеристика: {current_key} = {value}")
                    else:
                        logger.warning(f"Неизвестный или отсутствующий ключ для значения: {value}. Пропускаем.")
                else:
                    # Предполагаем, что это ключ
                    if line in valid_keys:
                        current_key = line
                        logger.info(f"Найден ключ: {current_key}")
                    else:
                        logger.warning(f"Строка не соответствует ожидаемым ключам: {line}. Пропускаем.")

    except NoSuchElementException:
        logger.error("Не удалось найти элемент с характеристиками.")
    except Exception as e:
        logger.error(f"Ошибка при извлечении характеристик: {e}")

    logger.info(f"Итоговые характеристики: {characteristics}")
    return characteristics

def extract_prices(driver, logger):
    prices = {}
    try:
        # Найти таблицу с ценами на поликарбонат
        try:
            poly_table = driver.find_element(By.CSS_SELECTOR, "table.tb2.adaptive.poly-price")
            headers = poly_table.find_elements(By.TAG_NAME, "th")
            lengths = []
            for header in headers[1:]:  # Пропускаем первый <th> (Материал)
                length_text = header.text.strip().lower().replace('\xa0', ' ')
                # Проверяем, содержит ли заголовок цифры
                if not re.search(r'\d', length_text):
                    logger.warning("Обнаружен пустой или некорректный заголовок длины. Пропускаем.")
                    continue
                # Учитываем разные варианты написания
                if re.search(r'4\s*метров|4\s*метра|4\s*м', length_text):
                    lengths.append('4 метров')
                elif re.search(r'6\s*метров|6\s*метра|6\s*м', length_text):
                    lengths.append('6 метров')
                elif re.search(r'8\s*метров|8\s*метра|8\s*м', length_text):
                    lengths.append('8 метров')
                elif re.search(r'10\s*метров|10\s*метра|10\s*м', length_text):
                    lengths.append('10 метров')
                elif re.search(r'12\s*метров|12\s*метра|12\s*м', length_text):
                    lengths.append('12 метров')
                else:
                    lengths.append(length_text)  # Для нестандартных длин
            logger.info(f"Определены длины поликарбоната: {lengths}")

            rows = poly_table.find_elements(By.TAG_NAME, "tr")
            for row in rows[1:]:
                cols = row.find_elements(By.TAG_NAME, "td")
                expected_cols = len(lengths) + 1  # +1: Материал
                if len(cols) < expected_cols:
                    logger.warning(f"Количество столбцов в строке не соответствует ожидаемому. Строка: {row.text}")
                    continue
                material = cols[0].text.strip()
                for idx, col in enumerate(cols[1:1+len(lengths)], start=0):
                    if idx < len(lengths):
                        length = lengths[idx]
                        key = f"Поликарбонат Стандарт 4мм ({length})"
                        value = col.text.strip()
                        if value:
                            prices[key] = value
                            logger.info(f"Извлечена цена: {key} = {value}")
                        else:
                            logger.warning(f"Цена для {key} отсутствует.")
        except NoSuchElementException:
            logger.warning("Таблица с ценами на поликарбонат не найдена.")

        # Извлечение цен на дополнительные стяжки и фундамент
        try:
            # Предполагается, что таблицы для стяжек и фундамента имеют определённые заголовки
            tables = driver.find_elements(By.CSS_SELECTOR, "table.tb2.adaptive")
            for table in tables:
                headers = table.find_elements(By.TAG_NAME, "th")
                if not headers:
                    continue
                first_header = headers[0].text.strip().lower()
                if "стяжки" in first_header:
                    # Обработка таблицы стяжек
                    rows = table.find_elements(By.TAG_NAME, "tr")
                    for row in rows[1:]:
                        cols = row.find_elements(By.TAG_NAME, "td")
                        if len(cols) >= 2:
                            key = f"Цена 1 стяжки {cols[0].text.strip()}"
                            value = cols[1].text.strip()
                            if value:
                                prices[key] = value
                                logger.info(f"Извлечена цена: {key} = {value}")
                            else:
                                logger.warning(f"Цена для {key} отсутствует.")
                elif "фундамент" in first_header:
                    # Обработка таблицы фундамента
                    rows = table.find_elements(By.TAG_NAME, "tr")
                    for row in rows[1:]:
                        cols = row.find_elements(By.TAG_NAME, "td")
                        if len(cols) >= 2:
                            key = f"Цена фундамента {cols[0].text.strip()}"
                            value = cols[1].text.strip()
                            if value:
                                prices[key] = value
                                logger.info(f"Извлечена цена: {key} = {value}")
                            else:
                                logger.warning(f"Цена для {key} отсутствует.")
        except Exception as e:
            logger.error(f"Ошибка при извлечении цен на стяжки и фундамент: {e}")

    except Exception as e:
        logger.error(f"Ошибка при извлечении цен: {e}")
    return prices

def extract_teplitsa_data(driver, url, logger, retries=3):
    data = {}
    attempt = 0
    while attempt < retries:
        try:
            driver.get(url)
            logger.info(f"\nПереходим по ссылке: {url}")
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            if not is_page_available(driver, logger):
                logger.warning(f"Страница {url} не найдена (404). Пропускаем.")
                return None
            try:
                title_element = driver.find_element(By.XPATH, "//h1")
                data["Название"] = title_element.text.strip()
                logger.info(f"Извлечено название: {data['Название']}")
            except NoSuchElementException:
                data["Название"] = "Не указано"
                logger.warning("Не удалось извлечь название.")
            characteristics = extract_characteristics(driver, logger)
            if characteristics:
                data.update(characteristics)
            prices = extract_prices(driver, logger)
            data["Цены"] = prices
            return data
        except WebDriverException as e:
            logger.error(f"WebDriverException: {e}. Попытка {attempt + 1} из {retries}. Перезапуск браузера.")
            attempt += 1
            driver.quit()
            driver = setup_driver()
            time.sleep(5)
        except (TimeoutException, Exception) as e:
            logger.error(f"Ошибка при извлечении данных из {url}: {e}. Попытка {attempt + 1} из {retries}.")
            attempt += 1
            time.sleep(5)
    logger.error(f"Не удалось извлечь данные из {url} после {retries} попыток.")
    return None

def main():
    csv_file = 'teplicy_links_final.csv'  # Ваш окончательный CSV-файл

    # Укажите путь к chromedriver, если он не добавлен в PATH
    chromedriver_path = None  # Например, 'C:/path/to/chromedriver.exe' для Windows или '/path/to/chromedriver' для macOS/Linux

    # Список городов (можно оставить, если нужны какие-то специфические настройки)
    cities = {
        "Москва": "msk",
        "Ставрополь": "stavropol",
        # Добавьте остальные города по необходимости
    }

    # Настройка глобального логирования (можно оставить или убрать, зависит от структуры логгеров для городов)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Инициализация WebDriver.")

    driver = setup_driver(chromedriver_path)
    logging.info("WebDriver успешно запущен.")

    all_links = read_links_from_csv(csv_file, logging)

    all_data = []

    for entry in all_links:
        name = entry['Название']
        city = entry['Город']
        city_code = entry['ГородКод']
        url = entry['URL']

        logger = setup_logging(city)
        logger.info(f"\nНачинаем обработку: {name} для города: {city}")

        data = extract_teplitsa_data(driver, url, logger)
        if data:
            data["Город"] = city
            all_data.append(data)
            logger.info(f"Данные для {name} в городе {city} успешно извлечены.")
        else:
            logger.warning(f"Данные для {name} в городе {city} не получены.")
        
        # Рандомная задержка между запросами
        time.sleep(random.uniform(1, 3))  # Задержка от 1 до 3 секунд

    driver.quit()
    logging.info("WebDriver закрыт.")
    print("\nWebDriver закрыт.")

    # Сохранение всех данных в один JSON-файл
    output_file = "teplicy_all_cities_data.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        logging.info(f"Сбор данных завершен. Результат сохранен в '{output_file}'.")
        print(f"Сбор данных завершен. Результат сохранен в '{output_file}'.")
    except Exception as e:
        logging.error(f"Ошибка при сохранении JSON файла: {e}")
        print(f"Ошибка при сохранении JSON файла: {e}")

if __name__ == "__main__":
    main()
