#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
car_kb.py — база знаний по машине. Данные: car_kb.json рядом со скриптом.

Команды:
  python car_kb.py add "категория" "текст"   — добавить факт
      категории: авто, эбу, сканер, диагностика, ремонт, план, наблюдение
  python car_kb.py show                      — показать всю базу
  python car_kb.py sync [файлы отчётов]      — влить метрики из отчётов logscan
  python car_kb.py brief                     — брифинг для вставки в новый диалог
  python car_kb.py backup                    — копия car_kb.json с датой
  python car_kb.py del "категория" "текст"   — удалить записи, содержащие текст
  python car_kb.py list [категория]          — пронумерованный список записей
"""

import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime

KB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "car_kb.json")

CATS = ("авто", "эбу", "сканер", "диагностика", "ремонт", "план", "наблюдение")

def load():
    if not os.path.exists(KB_FILE):
        print("(car_kb.json не найден — создаю пустую базу)")
        save({})
        return {}
    with open(KB_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            f.seek(0)
            try:
                data = json.load(f, strict=False)  # прощает сырые \n и \t внутри строк
                print("(car_kb.json содержал управляющие символы, прочитал в щадящем режиме)")
                return data
            except json.JSONDecodeError:
                f.seek(0)
                raw = f.read()
            backup = KB_FILE.replace(".json", ".broken.json")
            with open(backup, "w", encoding="utf-8") as bf:
                bf.write(raw)
            print("car_kb.json не читается! Копия сохранена как {}. JSONDecodeError: {}".format(backup, e))
            raise SystemExit(1)


def save(kb):
    with open(KB_FILE, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)


def cmd_add(cat, text):
    cat, text = cat.strip().lower(), text.strip()
    if cat not in CATS:
        print("Неизвестная категория '{}'. Доступны: {}".format(cat, ", ".join(CATS)))
        return
    kb = load()
    kb.setdefault(cat, [])
    if text in kb[cat]:
        print("Уже есть в '{}', не дублирую.".format(cat))
        return
    kb[cat].append(text)
    save(kb)
    print("Записал в '{}': {}".format(cat, text))


def fmt_metrics(met):
    lines = []
    for fname, m in sorted(met.items()):
        pairs = ["{}={}".format(k, v) for k, v in sorted(m.items())
                 if not k.startswith("_")]
        lines.append("  [{}] {}".format(fname, "; ".join(pairs)))
    return lines


def cmd_show():
    kb = load()
    for cat in [c for c in CATS if c in kb] + [c for c in kb if c not in CATS]:
        print("== {} ==".format(cat))
        if cat == "метрики" and isinstance(kb[cat], dict):
            for line in fmt_metrics(kb[cat]):
                print(line)
        else:
            for v in kb[cat]:
                print("  - " + str(v))
        print()


def cmd_sync(paths):
    kb = load()
    met = kb.setdefault("метрики", {})
    added = 0
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(p, encoding="cp1251") as f:
                text = f.read()
        for block in text.split("=" * 72):
            m = re.search(r"Файл:\s*(\S+?\.csv)", block)
            if not m:
                continue
            fname = m.group(1)
            metrics = {}

            def rx(pat, cast=str):
                mm = re.search(pat, block)
                return cast(mm.group(1)) if mm else None

            v = rx(r"MAP на ХХ $прогретый$.*медиана (\d+)", int)
            if v is not None: metrics["MAP_хх_прогретый_мбар"] = v
            v = rx(r"MAP на ХХ $холодный$.*медиана (\d+)", int)
            if v is not None: metrics["MAP_хх_холодный_мбар"] = v
            v = rx(r"противофаза (\d+)%", int)
            if v is not None: metrics["противофаза_лямбд_pct"] = v
            v = rx(r"Нижняя лямбда на ХХ: медиана (\d+)", int)
            if v is not None: metrics["нижняя_лямбда_хх_мв"] = v
            v = rx(r"Флаг Errors: 1 в \d+ из \d+ строк $(\d+)%$", int)
            if v is not None: metrics["errors_flag_pct"] = v
            v = rx(r"прогретом ХХ $ОЖ>=70$: медиана (\d+)", int)
            if v is not None: metrics["лямбда_прогретый_хх_мв"] = v
            v = rx(r"прогретом ХХ.*ниже 200 мВ в (\d+)%", int)
            if v is not None: metrics["лямбда_прогретый_доля_200_pct"] = v
            v = rx(r"ТНВД: рампа [\d.…]+ бар $медиана (\d+)$", int)
            if v is not None: metrics["тнвд_рампа_медиана"] = v
            v = rx(r"Регулятор ТНВД: [\d.…]+% $медиана (\d+)%$", int)
            if v is not None: metrics["тнвд_регулятор_медиана"] = v
            v = rx(r"Детонация: макс сенсор ([\d.]+)", float)
            if v is not None: metrics["детонация_макс"] = v
            v = rx(r"превышений порога: (\d+)", int)
            if v is not None: metrics["детонация_превышений"] = v
            v = rx(r"движение мин ([\d.]+) В", float)
            if v is not None: metrics["батарея_движение_мин"] = v
            v = rx(r"зажигание/пуск мин ([\d.]+) В", float)
            if v is not None: metrics["батарея_пуск_мин"] = v
            v = rx(r"Атмосфера: (\d+)", int)
            if v is not None: metrics["атмосфера_мбар"] = v
            v = rx(r"медианный шаг ([\d.]+) с", float)
            if v is not None: metrics["шаг_записи_с"] = v
            n = len(re.findall(r"СТОЙКИЙ", block))
            if n: metrics["стойких_недоборов"] = n
            if metrics:
                metrics["_обновлено"] = datetime.now().strftime("%Y-%m-%d")
                met[fname] = metrics
                added += 1
    save(kb)
    print("Влил метрики из {} файлов (всего в базе: {}).".format(added, len(met)))


def cmd_brief():
    kb = load()
    lines = ["=== БРИФИНГ ПО МАШИНЕ (вставить первым сообщением в новый диалог) ==="]
    for cat in [c for c in CATS if c in kb] + [c for c in kb if c not in CATS and c != "метрики"]:
        if cat in kb:
            lines.append("-- {}: --".format(cat))
            for v in kb[cat]:
                lines.append("  " + str(v))
    if "метрики" in kb:
        lines.append("-- метрики по файлам: --")
        lines.extend(fmt_metrics(kb["метрики"]))
    text = "\n".join(lines)
    print(text)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "брифинг_машины.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("(копия сохранена: {})".format(out))


def cmd_backup():
    if os.path.exists(KB_FILE):
        dst = KB_FILE.replace(".json", "_" +
                              datetime.now().strftime("%Y%m%d") + ".json")
        shutil.copy2(KB_FILE, dst)
        print("Копия: " + dst)
    else:
        print("База ещё не создана — сначала add или sync.")


def cmd_del(cat, pattern):
    kb = load()
    if cat not in kb:
        print("Нет категории '{}'.".format(cat))
        return
    before = len(kb[cat])
    kb[cat] = [v for v in kb[cat] if pattern.lower() not in str(v).lower()]
    save(kb)
    print("Удалил {} записей из '{}'.".format(before - len(kb[cat]), cat))


def cmd_list(cat=None):
    kb = load()
    for c in sorted(kb):
        if cat and cat != c:
            continue
        print("[{}] ({})".format(c, len(kb[c])))
        if c == "метрики" and isinstance(kb[c], dict):
            for fname, m in kb[c].items():
                print("  - {} ({} полей)".format(fname, len(m)))
        else:
            for i, v in enumerate(kb[c]):
                print("  {}. {}".format(i + 1, v[:150]))


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    cmd = a[0]
    if cmd == "add" and len(a) >= 3:
        cmd_add(a[1], " ".join(a[2:]))
    elif cmd == "show":
        cmd_show()
    elif cmd == "sync":
        files = a[1:] or sorted(glob.glob("отчёт*.txt"))
        if files:
            cmd_sync(files)
        else:
            print("Нет файлов отчётов для синхронизации.")
    elif cmd == "brief":
        cmd_brief()
    elif cmd == "backup":
        cmd_backup()
    elif cmd == "del" and len(a) >= 3:
        cmd_del(a[1], " ".join(a[2:]))
    elif cmd == "list":
        cmd_list(a[1] if len(a) > 1 else None)
    else:
        print("Не понял команду '{}'. Запустите без аргументов — покажу справку.".format(cmd))


if __name__ == "__main__":
    main()
