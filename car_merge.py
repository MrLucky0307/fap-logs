# -*- coding: utf-8 -*-
# car_merge.py v2.1 — склейка повторных выгрузок суточного лога FAP в один канонический файл.
# Запуск: python car_merge.py
# Что делает:
#   1. Ищет в текущей папке файлы MED17_4_2_YYYYMMDD*.csv (все выгрузки одного дня).
#   2. Убирает повторяющиеся строки, сортирует по дате и времени.
#   3. Записывает канонический MED17_4_2_YYYYMMDD.csv.
#   4. Все исходные выгрузки, кроме канонического, переносит в папку raw/.
# Файлы не удаляются — только переносятся, ничего не теряется.
#
# Что нового в v2 относительно v1:
#   - строки-шапки (Date;...) из повторных выгрузок больше не попадают в
#     канонический файл как данные (раньше в каноне оказывались две шапки);
#   - сортировка по дате+времени: ночная сессия через полночь не перемешивается;
#   - предупреждение о РАЗНЫХ ШАПКАХ у выгрузок (несовместимые строки не смешиваются молча);
#   - подсчёт коллизий времени (разные данные на одну метку — как у глитчей ELM);
#   - подсчёт строк с числом колонок, отличным от шапки;
#   - первая строка файла-продолжения (-1) не теряется, если это данные, а не шапка:
#     строки данных до первой шапки буферизуются и подшиваются после её обнаружения;
#     если шапки нет ни в одном файле — громкое предупреждение.

import os, glob, re, shutil

def detect_delimiter(line):
    for d in (";", ",", "\t"):
        if d in line:
            return d
    return ";"

def cells(line, delim):
    return [c.strip().strip('"') for c in line.split(delim)]

def is_header(line, delim):
    cs = cells(line, delim)
    if not cs:
        return False
    first = cs[0].lower()
    return first == "date" or first.startswith("дата")

def time_col_index(header, delim):
    names = cells(header, delim)
    for i, h in enumerate(names):
        hl = h.lower()
        if hl in ("time", "timestamp", "время") or "time" in hl or "время" in hl:
            return i, names[i]
    return None, None

def date_col_index(header, delim):
    names = cells(header, delim)
    for i, h in enumerate(names):
        if h.lower() == "date" or h.lower().startswith("дата"):
            return i
    return None

def to_seconds(t):
    # "12:34:56" или "12:34:56.7" -> секунды; если уже число — вернём как есть
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

DATE_YMD = re.compile(r'^(\d{4})[.\-/](\d{2})[.\-/](\d{2})$')   # 2026.10.11
DATE_DMY = re.compile(r'^(\d{2})[.\-/](\d{2})[.\-/](\d{4})$')   # 11.10.2026

def to_daynum(s):
    # -> (y, m, d) или None; None сортируется первым (строки без даты — в начале)
    s = s.strip().strip('"')
    m = DATE_YMD.match(s)
    if m:
        y, mo, d = map(int, m.groups())
        return (y, mo, d)
    m = DATE_DMY.match(s)
    if m:
        d, mo, y = map(int, m.groups())
        return (y, mo, d)
    return None

ZERO = (0, 0, 0)

def main():
    files = []
    for pat in ("MED17_4_2_????????.csv", "MED17_4_2_????????*.csv"):
        for f in sorted(glob.glob(pat)):
            if f not in files:
                files.append(f)
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
        if canon in flist:
            flist = [canon] + sorted(f for f in flist if f != canon)
        else:
            flist = sorted(flist)

        header = None
        delim = ";"
        ncols = 0
        tcol, tname, dcol = None, None, None
        seen = set()
        time_seen = {}
        rows = []      # (daynum, sec, порядок, line)
        n_in = 0
        collisions = 0
        bad_cols = 0
        pending = []   # строки данных, встреченные до первой шапки

        def set_header(line):
            nonlocal delim, header, tcol, tname, dcol, ncols
            delim = detect_delimiter(line)
            header = line
            tcol, tname = time_col_index(header, delim)
            dcol = date_col_index(header, delim)
            ncols = len(cells(header, delim))

        def add_data(line):
            nonlocal n_in, collisions, bad_cols
            if line in seen:
                return
            seen.add(line)
            parts = line.split(delim)
            if len(parts) != ncols:
                bad_cols += 1
            sec = to_seconds(parts[tcol]) if (tcol is not None and tcol < len(parts)) else None
            dnum = to_daynum(parts[dcol]) if (dcol is not None and dcol < len(parts)) else None
            if sec is not None and dnum is not None:
                tkey = (dnum, sec)
                if tkey in time_seen and time_seen[tkey] != line:
                    collisions += 1
                time_seen[tkey] = line
            rows.append((dnum or ZERO, sec if sec is not None else 0.0, len(rows), line))

        def flush_pending():
            for pl in pending:
                add_data(pl)
            pending.clear()

        for f in flist:
            with open(f, "r", encoding="utf-8-sig", errors="replace") as fh:
                for line in fh:
                    line = line.rstrip("\r\n")
                    if not line.strip():
                        continue
                    if header is None:
                        if is_header(line, detect_delimiter(line)):
                            set_header(line)
                            flush_pending()
                        else:
                            pending.append(line)   # данные до шапки — копим
                            n_in += 1
                        continue
                    if is_header(line, delim):
                        if cells(line, delim) != cells(header, delim):
                            print("[!!] {}: РАЗНЫЕ ШАПКИ — строки этого файла могут не "
                                  "соответствовать каноническому набору колонок".format(f))
                        continue
                    n_in += 1
                    add_data(line)

        if header is None and pending:
            print("[!!] {}: шапки нет ни в одном файле — первая строка данных "
                  "принята за шапку, проверьте файл вручную".format(day))
            set_header(pending[0])
            flush_pending()

        # сортировка по дате и времени (устойчивая: без даты/времени — по порядку следования)
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
        n_out = len(rows)

        with open(canon, "w", encoding="utf-8", newline="") as fh:
            fh.write(header + "\n")
            for _, _, _, line in rows:
                fh.write(line + "\n")

        # убираем исходники в raw/
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
        if tname:
            print("  сортировка по колонке: {} (+ дата)".format(tname))
        else:
            print("  колонка времени не найдена — порядок сохранён как в файлах")
        if collisions:
            print("  [!!] коллизий времени (разные данные на одну метку): {}".format(collisions))
        if bad_cols:
            print("  [~] строк с числом колонок, отличным от шапки: {}".format(bad_cols))

    print("Готово. Всего убрано повторов: {}".format(total_removed))

if __name__ == "__main__":
    main()
