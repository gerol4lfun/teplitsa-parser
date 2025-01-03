from selenium import webdriver
from selenium.webdriver.common.by import By
import time

def main():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    # Обратите внимание: НЕ передаём executable_path и Service
    driver = webdriver.Chrome(options=options)

    url = "https://teplitsa-rus.ru/..."  # ваша ссылка
    driver.get(url)
    time.sleep(3)
    driver.save_screenshot("debug_screenshot.png")
    driver.quit()
    print("Готово, скриншот сделан.")

if __name__ == "__main__":
    main()
