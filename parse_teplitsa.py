from selenium import webdriver
from selenium.webdriver.common.by import By
import pandas as pd
import time

# Путь к ChromeDriver
driver_path = "./chromedriver"

# Настройка браузера
options = webdriver.ChromeOptions()

# Новая настройка сервиса
from selenium.webdriver.chrome.service import Service
service = Service(driver_path)
driver = webdriver.Chrome(service=service, options=options)

# URL сайта
url = "https://teplitsa-rus.ru"

# Открываем сайт
driver.get(url)
time.sleep(3)  # Ждём, пока сайт загрузится

# Сбор данных о теплицах
data = []

try:
    # Найдите элементы каталога (замените на реальные селекторы)
    catalog_items = driver.find_elements(By.CLASS_NAME, "catalog-item-class")  # Замените "catalog-item-class"
    for item in catalog_items:
        # Извлекаем название теплицы
        name = item.find_element(By.CLASS_NAME, "item-name-class").text  # Замените "item-name-class"
        
        # Извлекаем цены
        prices = item.find_elements(By.CSS_SELECTOR, 'td[data-label$="метра"]')
        for price in prices:
            length = price.get_attribute("data-label")  # Длина (4 метра, 6 метров и т.д.)
            value = price.text  # Цена (например, 18990 руб.)
            
            # Выводим для отладки
            print(f"Название: {name}, Длина: {length}, Цена: {value}")
            
            # Добавляем данные
            data.append({"Название": name, "Длина": length, "Цена": value})

except Exception as e:
    print(f"Ошибка: {e}")

finally:
    # Закрываем браузер
    driver.quit()

# Сохраняем данные в CSV
df = pd.DataFrame(data)
df.to_csv("teplitsa_data.csv", index=False)
print("Данные сохранены в teplitsa_data.csv")
