# car_repair.py — спасение базы знаний из сломанного car_kb.json
import json, re

BASE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE, "raw")

def find_csvs():
    files = sorted(glob.glob(os.path.join(RAW_DIR, "MED17*.csv")))
    if not files:
        print(f"CSV-файлы MED17_4_2_YYYYMMDD.csv не найдены в папке {RAW_DIR}")
        print("Создайте папку raw рядом со скриптом и скопируйте логи туда.")
    return files

DST = "car_kb.json"
CANDS = ["car_kb.broken.json", "car_kb.json"]

raw, src = None, None
for fn in CANDS:
    try:
        with open(fn, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        src = fn
        break
    except OSError:
        pass
if raw is None:
    print("Не нашёл ни car_kb.broken.json, ни car_kb.json — спасать нечего?")
    raise SystemExit(1)
print("Источник: {} ({} символов)".format(src, len(raw)))

# Шаг 1: обычные разборы
kb = None
for name, kwargs in (("строгий", {}), ("щадящий", {"strict": False})):
    try:
        kb = json.loads(raw, **kwargs)
        print("Разобралось в {} режиме — файл цел, восстановление не нужно.".format(name))
        break
    except json.JSONDecodeError as e:
        print("Разбор {} не прошёл: {}".format(name, e))

# Шаг 2: построчная реконструкция dict[категория -> список записей]
if kb is None:
    try:
        json.loads(raw)
    except json.JSONDecodeError as e:
        frag = raw[max(0, e.pos - 150):e.pos + 150]
        print("---- фрагмент вокруг аварии ----")
        print(frag.replace("\r", "<CR>"))
        print("---- конец фрагмента ----")

    kb, cat, buf = {}, None, None
    for line in raw.splitlines():
        s = line.strip()
        if buf is not None:                      # копим оборванную запись
            if s.endswith('",') or s.endswith('"'):
                val = buf + " " + s
                val = val[1:].rstrip(",")
                if val.endswith('"'):
                    val = val[:-1]
                if cat is not None and val.strip():
                    kb[cat].append(val.strip())
                buf = None
            else:
                buf += " " + s
            continue
        m = re.match(r'^"(.+?)":\s*\[$', s)
        if m:
            cat = m.group(1)
            kb.setdefault(cat, [])
            continue
        if s in ("{", "}", "]", "],", ""):
            continue
        if s.startswith('"') and (s.endswith('",') or s.endswith('"')):
            val = s[1:].rstrip(",")
            if val.endswith('"'):
                val = val[:-1]
            if cat is not None and val.strip():
                kb[cat].append(val.strip())
        elif s.startswith('"'):
            buf = s                              # запись разрезана строкой — собираем
    if buf is not None and cat is not None and len(buf) > 3:
        kb[cat].append(buf[1:].strip())
        print("Последняя запись была оборвана — сохранил урезанной: {!r}...".format(buf[1:].strip()[:80]))

    total = sum(len(v) for v in kb.values())
    print("Построчная реконструкция: категорий {}, записей {}".format(len(kb), total))
    if total == 0:
        print("Спасать нечего — вот файл целиком, чинить будем руками:")
        print(raw)
        raise SystemExit(1)

# Шаг 3: показать и записать
total = sum(len(v) for v in kb.values())
for c in kb:
    print("\n[{}] ({})".format(c, len(kb[c])))
    for i, v in enumerate(kb[c]):
        print("  {}. {}".format(i + 1, v[:120]))

with open(DST, "w", encoding="utf-8") as f:
    json.dump(kb, f, ensure_ascii=False, indent=2)
print("\nПерезаписал {}: {} категорий, {} записей. car_kb.py снова рабочий.".format(DST, len(kb), total))
