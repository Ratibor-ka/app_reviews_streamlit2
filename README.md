# App Store Reviews Scraper — Streamlit

## Запуск

```bash
pip install streamlit requests pandas
streamlit run app.py
```

Или через Docker / Streamlit Cloud.

## Возможности
- Ввод App ID или ссылки App Store
- Слайдер количества (1–500)
- Выбор страны из 18 регионов
- Выбор полей для экспорта
- Скачивание в форматах **CSV** и **XML**
- Предпросмотр таблицы
- Диаграмма распределения рейтингов
- Лог выполнения

## Ограничение
iTunes RSS API: до 500 отзывов на страну.
