# -*- coding: utf-8 -*-
# car_merge.py v2 — склейка повторных выгрузок суточного лога FAP в один канонический файл.
# Запуск: python car_merge.py
# Что делает:
#   1. Ищет в текущей папке файлы MED17_4_2_YYYYMMDD*.csv (все выгрузки одного дня).
#   2. Убирает повторяющиеся строки (включая шапки повторных выгрузок), сортирует по дате+времени.
#   3. Записывает канонический MED17_4_2_YYYYMMDD.csv.
#   4. Все исходные выгрузки, кроме канонического, переносит в папку raw/.
# Файлы не удаляются — только переносятся, ничего не теряется.
#
# Что нового в v2 относительно v1:
#   - шапки повторных выгрузок больше не попадают в канонический файл строкой данных;
#   - сортировка по ДАТЕ+времени: ночная сессия через полночь больше не перемешивается
#     со строками утра того же дня;
#   - предупреждение, если у выгрузок разный набор колонок (шапки не совпали);
#   - подсчёт строк с коллизией времени (разные данные на одну метку);
#   - предупреждение о строках с числом колонок, не совпадающим с шапкой;
#   - убран неиспользуемый import csv.

import os, glob, re, shutil

def detect_delimiter(line):
    for d in (";", ",", "\t"):
        if d in line:
            return d
    return ";"

def split_cols(line, delim):
    return [c.strip().strip('"') for c in line.split(delim)]

def time_col_index(header, delim):
    names = split_cols(header, delim)
    for i, h in enumerate(names):
        hl = h.lower()
        if hl in ("time", "timestamp", "время") or "time" in hl or "время" in hl:
            return i, names[i]
    return None, None

def date_col_index(header, delim):
    names = split_cols(header, delim)
    for i, h in enumerate(names):
        if h.lower() in ("date", "дата"):
            return i
    return None

def to_seconds(t):
    t = t.strip().strip('"')
    m = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?$', t)
    if m:
        h, mi, s, frac = m.groups()
        sec = int(h) * 3600 + int(mi) * 60 + (int(s) if s else 0)
        if frac:
            sec += float("0." + frac)
        return sec
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None

def to_date_ordinal(d):
    d = d.strip().strip('"')
    m = re.match(r'^(\d{4})\.(\d{2})\.(\d{2})$', d)
    if not m:
        return None
    y, mo, da = (int(x) for x in m.groups())
    try:
        import datetime as _dt
        return _dt.date(y, mo, da).toordinal()
    except ValueError:
        return None

def is_header_line(line, delim, first_cell):
    cols = line.split(delim)
    c0 = cols[0].strip().strip('"').lower() if cols else ""
    return c0 == "date" or (first_cell is not None and c0 == first_cell.lower())

def main():
    files = sorted(glob.glob("MED17_4_2_????????.csv")) + \
            sorted(f for f in glob.glob("MED17_4_2_????????*.csv")
                   if not re.match(r'MED17_4_2_\d{8}\.csv$', os.path.basename(f)))
    groups = {}
    for f in files:
        m = re.match(r'MED17_4_2_(\d{8})', os.path.basename(f))
        if m:
            groups.setdefault(m.group(1), []).append(f)

    if not groups:
        print("Файлов MED17_4_2_*.csv не найдено — делать нечего.")
        return

    total_removed = 0
    for day, flist in sorted(groups.items()):
        canon = "MED17_4_2_{}.csv".format(day)
        flist = [canon] + sorted(f for f in flist if f != canon) if canon in flist else sorted(flist)

        header = None
        delim = ";"
        tcol = tname = dcol = None
        first_cell = None
        seen = set()
        rows = []      # (sort_key, line)
        n_in = 0
        n_coll = 0
        n_badcol = 0
        header_warn = []

        for f in flist:
            with open(f, "r", encoding="utf-8-sig", errors="replace") as fh:
                first = fh.readline()
                if header is None:
                    delim = detect_delimiter(first)
                    header = first.rstrip("\r\n")
                    tcol, tname = time_col_index(header, delim)
                    dcol = date_col_index(header, delim)
                    first_cell = split_cols(header, delim)[0] if split_cols(header, delim) else None
                    seen.add(header)          # шапка канонического файла — тоже дубликат
                else:
                    fhdr = first.rstrip("\r\n")
                    if fhdr and fhdr != header:
                        header_warn.append(os.path.basename(f))

                for line in fh:
                    line = line.rstrip("\r\n")
                    if not line.strip():
                        continue
                    n_in += 1
                    if is_header_line(line, delim, first_cell):
                        continue               # повторная шапка выгрузки — мусор
                    if line in seen:
                        continue
                    seen.add(line)
                    cols = split_cols(line, delim)
                    if header is not None and len(cols) != len(split_cols(header, delim)):
                        n_badcol += 1
                    if tcol is not None and tcol < len(cols):
                        sec = to_seconds(cols[tcol])
                    else:
                        sec = None
                    dord = to_date_ordinal(cols[dcol]) if (dcol is not None and dcol < len(cols)) else None
                    if dord is not None:
                        key = (dord, sec if sec is not None else 0, len(rows))
                    else:
                        key = (sec if sec is not None else 0, len(rows))
                    rows.append((key, line))

        # контроль коллизий: одна метка времени — разные данные
        if tcol is not None and dcol is not None:
            from collections import defaultdict
            byts = defaultdict(list)
            for key, line in rows:
                byts[key[:2]].append(line)
            n_coll = sum(len(v) - 1 for v in byts.values() if len(v) > 1)

        rows.sort(key=lambda r: r[0])
        n_out = len(rows)

        with open(canon, "w", encoding="utf-8", newline="") as fh:
            fh.write(header + "\n")
            for _, line in rows:
                fh.write(line + "\n")

        os.makedirs("raw", exist_ok=True)
        moved = []
        for f in flist:
            if f != canon and os.path.exists(f):
                dst = os.path.join("raw", f)
                i = 1
                while os.path.exists(dst):
                    base, ext = os.path.splitext(f)
                    dst = os.path.join("raw", "{}_{}{}".format(base, i, ext))
                    i += 1
                shutil.move(f, dst)
                moved.append(os.path.basename(dst))

        total_removed += (n_in - n_out)
        print("{}: файлов {}, строк {} -> {} (убрано {} повторов)".format(
            day, len(flist), n_in, n_out, n_in - n_out))
        print("  канонический: {}".format(canon))
        if moved:
            print("  в raw/: " + ", ".join(moved))
        if header_warn:
            print("  [!!] РАЗНЫЕ ШАПКИ у выгрузок: {} — строки с другим набором колонок смешаны!".format(", ".join(header_warn)))
        if n_badcol:
            print("  [~] строк с числом колонок, отличным от шапки: {}".format(n_badcol))
        if n_coll:
            print("  [~] коллизий времени (разные данные на одну метку): {}".format(n_coll))
        if dcol is not None:
            print("  сортировка по: Дата+{}".format(tname))
        elif tname:
            print("  сортировка по колонке: {} (колонки Дата нет)".format(tname))
        else:
            print("  колонка времени не найдена — порядок сохранён как в файлах")

    print("Готово. Всего убрано повторов: {}".format(total_removed))

if __name__ == "__main__":
    main()
