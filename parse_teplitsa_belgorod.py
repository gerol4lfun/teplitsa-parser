import json
import time
import re
import random  # Добавленный импорт
import logging  # Добавленный импорт
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# Настройка логирования
logging.basicConfig(
    filename='teplicy_parser_belgorod.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Раскомментируйте для headless режима
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")
    # Опционально: изменение User-Agent для имитации реального пользователя
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def is_page_available(driver):
    try:
        if "404" in driver.title:
            return False
        driver.find_element(By.XPATH, "//h1[contains(text(), '404')]")
        return False
    except NoSuchElementException:
        return True

def construct_url(city_code, path):
    if path.endswith('.html'):
        path = path[:-5]
    if not path.endswith('/'):
        path += '/'
    base_url = f"https://{city_code}.teplitsa-rus.ru/"
    full_url = f"{base_url}{path}"
    return full_url

def extract_characteristics(driver):
    characteristics = {}
    # Определяем допустимые ключи характеристик
    valid_keys = {
        "Каркас",
        "Ширина",
        "Высота",
        "Снеговая нагрузка",
        "Горизонтальные стяжки",
        "Комплектация"
    }
    
    try:
        # Находим div с характеристиками
        desc_div = driver.find_element(By.CSS_SELECTOR, "div.prod_desc")
        desc_html = desc_div.get_attribute("innerHTML")
        
        # Парсим HTML с помощью BeautifulSoup
        soup = BeautifulSoup(desc_html, "html.parser")
        for br in soup.find_all("br"):
            br.replace_with("\n")  # Заменяем <br> на новую строку
        
        # Извлекаем текст и разделяем его на строки
        desc_text = soup.get_text(separator="\n")
        lines = [line.strip() for line in desc_text.split("\n") if line.strip()]
        
        logging.info("Извлеченные строки характеристик:")
        for line in lines:
            logging.info(f"  - {line}")
        
        # Обрабатываем строки по две
        i = 0
        while i < len(lines) - 1:
            key_line = lines[i]
            value_line = lines[i + 1]
            
            # Проверяем, что значение начинается с двоеточия
            if value_line.startswith(":"):
                key = key_line
                value = value_line[1:].strip()  # Убираем двоеточие и лишние пробелы
                if key in valid_keys:
                    characteristics[key] = value
                    logging.info(f"Извлечена характеристика: {key} = {value}")
                else:
                    logging.warning(f"Неизвестный ключ: {key}. Пропускаем.")
                i += 2  # Переходим к следующим двум строкам
            else:
                logging.warning(f"Строка не соответствует ожидаемому формату: {key_line} и {value_line}. Пропускаем.")
                i += 1  # Переходим к следующей строке
        
    except NoSuchElementException:
        logging.error("Не удалось найти элемент с характеристиками (div.prod_desc).")
    except Exception as e:
        logging.error(f"Ошибка при извлечении характеристик: {e}")
    
    logging.info(f"Итоговые характеристики: {characteristics}")
    return characteristics

def extract_prices(driver):
    prices = {}
    try:
        # Извлечение цен на поликарбонат
        try:
            poly_table = driver.find_element(By.CSS_SELECTOR, "table.tb2.adaptive.poly-price")
            rows = poly_table.find_elements(By.TAG_NAME, "tr")
            for row in rows[1:]:  # Пропускаем заголовок таблицы
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) > 1:
                    material = cols[0].text.strip()
                    # Предполагаем, что столбцы содержат длину теплицы и соответствующую цену
                    for i in range(1, len(cols)):
                        length = f"{4 + 2 * (i - 1)} метра"
                        key = f"{material} ({length})"
                        value = cols[i].text.strip()
                        if value:
                            prices[key] = value
                            logging.info(f"Извлечена цена: {key} = {value}")
                        else:
                            logging.warning(f"Цена для {key} отсутствует.")
        except NoSuchElementException:
            logging.warning("Таблица с ценами на поликарбонат не найдена.")
    
        # Извлечение цен на дополнительные стяжки
        try:
            tie_tables = driver.find_elements(By.CSS_SELECTOR, "table.tb2.adaptive")
            for table in tie_tables:
                rows = table.find_elements(By.TAG_NAME, "tr")
                for row in rows[1:]:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) > 1:
                        header = cols[0].text.strip().lower()
                        if "стяжки" in header:
                            key = f"{cols[0].text.strip()} стяжка"
                            value = cols[1].text.strip()
                            if value:
                                prices[key] = value
                                logging.info(f"Извлечена цена: {key} = {value}")
                            else:
                                logging.warning(f"Цена для {key} отсутствует.")
        except NoSuchElementException:
            logging.warning("Таблица с ценами на стяжки не найдена.")
    
        # Извлечение цен на фундамент
        try:
            foundation_tables = driver.find_elements(By.CSS_SELECTOR, "table.tb2.adaptive")
            if foundation_tables:
                foundation_table = foundation_tables[-1]  # Предполагаем, что последняя таблица — фундамент
                rows = foundation_table.find_elements(By.TAG_NAME, "tr")
                for row in rows[1:]:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) > 1:
                        key = f"{cols[0].text.strip()} фундамент"
                        value = cols[1].text.strip()
                        if value:
                            prices[key] = value
                            logging.info(f"Извлечена цена: {key} = {value}")
                        else:
                            logging.warning(f"Цена для {key} отсутствует.")
            else:
                logging.warning("Таблицы с ценами на фундамент не найдены.")
        except NoSuchElementException:
            logging.warning("Таблица с ценами на фундамент не найдена.")
    
    except Exception as e:
        logging.error(f"Ошибка при извлечении цен: {e}")
    return prices

def extract_teplitsa_data(driver, url):
    data = {}
    try:
        driver.get(url)
        logging.info(f"\nПереходим по ссылке: {url}")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        if not is_page_available(driver):
            logging.warning(f"Страница {url} не найдена (404). Пропускаем.")
            return None
        try:
            title_element = driver.find_element(By.XPATH, "//h1")
            data["Название"] = title_element.text.strip()
            logging.info(f"Извлечено название: {data['Название']}")
        except NoSuchElementException:
            data["Название"] = "Не указано"
            logging.warning("Не удалось извлечь название.")
        characteristics = extract_characteristics(driver)
        if characteristics:
            data.update(characteristics)  # Обновляем данные характеристиками
        prices = extract_prices(driver)
        data["Цены"] = prices
    except TimeoutException:
        logging.error(f"Время ожидания загрузки страницы {url} истекло.")
    except Exception as e:
        logging.error(f"Ошибка при извлечении данных из {url}: {e}")
    return data

def main():
    cities = {
        "Белгород": "belgorod",
    }
    test_links = [
        "item/2-teplica-arochnaya-25m/",
        "item/6-teplica-arochnaya-3m-ctandart/"
    ]
    driver = setup_driver()
    logging.info("WebDriver успешно запущен.")
    all_data = []
    for city_name, city_code in cities.items():
        logging.info(f"\nОбработка города: {city_name}")
        print(f"\nОбработка города: {city_name}")  # Сохраняем также для консоли
        for path in test_links:
            url = construct_url(city_code, path)
            data = extract_teplitsa_data(driver, url)
            if data:
                data["Город"] = city_name
                all_data.append(data)
            else:
                logging.warning(f"Данные для теплицы по ссылке {url} не получены.")
                print(f"Данные для теплицы по ссылке {url} не получены.")  # Сохраняем также для консоли
            # Рандомная задержка между запросами для избежания блокировок
            time.sleep(random.uniform(2, 5))  # Задержка от 2 до 5 секунд
    driver.quit()
    logging.info("\nWebDriver закрыт.")
    print("\nWebDriver закрыт.")  # Сохраняем также для консоли
    try:
        with open("teplicy_belgorod_data.json", "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=4)
        logging.info("Сбор данных завершен. Результат сохранен в 'teplicy_belgorod_data.json'.")
        print("Сбор данных завершен. Результат сохранен в 'teplicy_belgorod_data.json'.")
    except Exception as e:
        logging.error(f"Ошибка при сохранении JSON файла: {e}")
        print(f"Ошибка при сохранении JSON файла: {e}")

if __name__ == "__main__":
    main()
