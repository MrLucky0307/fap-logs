# -*- coding: utf-8 -*-
"""
car_common.py — общие константы и утилиты проекта fap-logs.
Соглашение проекта: все CSV-логи лежат в папке raw рядом со скриптами.
Любой скрипт получает список логов через find_csvs().
"""
import sys, os, glob

BASE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE, "raw")

def find_csvs(extra_args=None):
    """Список MED17*.csv из raw. Аргументы командной строки имеют приоритет:
    python скрипт.py файл1.csv файл2.csv — обработаются только они."""
    if extra_args:
        return extra_args
    files = sorted(glob.glob(os.path.join(RAW_DIR, "MED17*.csv")))
    if not files:
        print(f"CSV-файлы MED17_4_2_YYYYMMDD.csv не найдены в папке {RAW_DIR}")
        print("Создайте папку raw рядом со скриптом и скопируйте логи туда.")
    return files
