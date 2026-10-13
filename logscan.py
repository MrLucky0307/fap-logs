#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logscan.py v2.2 — анализ CSV-логов FAP (MED17.4.2).

Запуск:
  python logscan.py                      — все MED17*.csv из текущей папки
  python logscan.py файл1.csv файл2.csv  — указанные файлы

Результат: отчёт_logscan.txt + вывод в консоль.

Что нового в v2.1 относительно v2.0:
  - лямбды UpO2Volt/DownO2Volt читаются как милливольты (вольты конвертируются);
  - детонация: нулевой порог отсекается как «канал не читался»;
  - давление масла: расхождение факт/задание считается только на прогретом
    масле (>=60 °C) + медиана расхождений;
  - AirCPress — это кондиционер (не турбина!);
  - AtmosphPress — база для пересчёта наддува в избыточный;
  - ECUtemp;
  - плотность записи: медианный шаг и максимальная пауза;
  - пустые ячейки НЕ переносятся между строками (плохой ELM: каждая строка сама по себе);
  - десятичный разделитель: и точка, и запятая.

Что нового в v2.2 относительно v2.1:
  - MAP на ХХ: точки idle-up кондиционера (дроссель >2.5%) отсеиваются и
    показываются отдельной строкой — MAP больше не задран кондиционером;
  - AirCPress — это давление хладагента в БАРАХ (было: «мбар» и мёртвый порог 500);
  - FuelPress / FuelPressInstr / FuelPressReg разведены: рампа, задание,
    регулятор ТНВД — все три выведены в отчёт (раньше затирали друг друга);
  - даты формата 2026.10.12 парсятся — многодневная сортировка работает;
  - время через полночь печатается как "+1д ЧЧ:ММ:СС";
  - нижняя лямбда отдельно на прогретом ХХ (ОЖ >= 70 °C).
"""

import glob
import os
import re
import statistics
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE, "raw")

def find_csvs():
    files = sorted(glob.glob(os.path.join(RAW_DIR, "MED17*.csv")))
    if not files:
        print(f"CSV-файлы MED17_4_2_YYYYMMDD.csv не найдены в папке {RAW_DIR}")
        print("Создайте папку raw рядом со скриптом и скопируйте логи туда.")
    return files

SEPS = [";", ",", "\t"]
OUT_FILE = "отчёт_logscan.txt"
SEP_LINE = "=" * 72
LIMITS = {"turbo": 3000, "turbo_instr": 3000, "map": 1500, "map_instr": 1500,
          "o2_up": 1200, "o2_down": 1200}


# ---------------------------------------------------------------- утилиты

def norm(h):
    return re.sub(r"[^a-z0-9а-я]", "", str(h).strip().lower())


def fnum(s):
    if s is None:
        return None
    s = str(s).strip().strip('"').replace("\xa0", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            return None
    if v != v:  # nan
        return None
    return v


def parse_date(s):
    s = str(s).strip().strip('"')
    for fmt in ("%Y.%m.%d", "%d-%m-%y", "%d.%m.%y", "%d/%m/%y", "%Y-%m-%d",
                "%d-%m-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(s):
    s = str(s).strip().strip('"')
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            t = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6
    return None


def tstr(t):
    t = int(t)
    days = t // 86400
    t %= 86400
    s = "{:02d}:{:02d}:{:02d}".format(t // 3600, t % 3600 // 60, t % 60)
    return ("+{}д ".format(days) + s) if days else s


def med(vals):
    return statistics.median(vals) if vals else None


# ------------------------------------------------------------- каналы

def channel_class(h):
    """Имя колонки -> ключ в словаре строки (или None/skip)."""
    h = norm(h)
    m = re.match(r"^inj(\d+)time$", h)
    if m:
        return ("inj", int(m.group(1)))
    if h == "upo2volt":
        return "o2_up"
    if h == "downo2volt":
        return "o2_down"
    if h == "br":
        return "brake"
    if h in ("upo2heat", "downo2heat"):
        return "skip"
    if h == "upmixcorr":
        return "up_corr"
    if h == "downmixcorr":
        return "down_corr"
    if h == "airmanifold":
        return "air_manifold"
    if h == "oiltemp":
        return "oil_temp"
    if h == "atmosphpress":
        return "atm"
    if h == "fuelpress":
        return "fuel_press"
    if h == "fuelpressinstr":
        return "fuel_press_instr"
    if h == "fuelpressreg":
        return "fuel_press_reg"
    if h == "alternatortemp":
        return "skip"
    if h == "alternatorcurrent":
        return "alt_current"
    if h == "ecutemp":
        return "ecu_temp"
    if h == "battery" or "напряжен" in h:
        return "battery"
    if h == "coolant" or "температураож" in h:
        return "coolant"
    if h == "aircpress" or "давление кондиционера" in h:
        return "ac_press"
    if h == "speed" or "скорост" in h:
        return "speed"
    if h == "gear":
        return "skip"
    if h == "fuellevel":
        return "fuel_level"
    if h == "externaltemp":
        return "ext_temp"
    if h == "intakeairpressinstr":
        return "map_instr"
    if h == "intakeairpress" or h == "map":
        return "map"
    if h in ("revs", "rpm") or "оборот" in h:
        return "rpm"
    if h == "turboinstr":
        return "turbo_instr"
    if h == "turbopress":
        return "turbo"
    if h == "oilpressinstr":
        return "oil_press_instr"
    if h == "oilpress":
        return "oil_press"
    if h == "airflowinstr":
        return "air_instr"
    if h == "airflow":
        return "air"
    if h == "throttleangleinstr":
        return "throttle_instr"
    if h == "throttleangle":
        return "throttle"
    if h.startswith("incamdephaser"):
        return "skip"
    if h.startswith("torq"):
        return "skip"
    if h == "turbowastegate":
        return "wastegate"
    if h == "turboblowoff":
        return "blowoff"
    if h == "accelpedalpos" or "педал" in h:
        return "pedal"
    if h in ("alternatorcharge", "oilpumpvalve"):
        return "skip"
    if h == "knocksensor":
        return "knock"
    if h == "knocksensorthr":
        return "knock_thr"
    if h in ("errors", "ошибки"):
        return "err"
    return None


# ------------------------------------------------------------- чтение

def load_csv(path):
    with open(path, "rb") as f:
        raw = f.read()
    text = None
    for enc in ("utf-8-sig", "cp1251", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return [], "", []

    tag = "FAP" if any("FAP" in l.upper() for l in lines[:2]) else ""
    header_line = lines[0]
    sep = max(SEPS, key=header_line.count)
    header = [c.strip().strip('"') for c in header_line.split(sep)]
    cls = [channel_class(c) for c in header]

    i_date = next((i for i, h in enumerate(header) if norm(h) == "date"), None)
    i_time = next((i for i, h in enumerate(header) if norm(h) == "time"), None)

    day_seen = {}
    points = []
    for line in lines[1:]:
        parts = [c.strip().strip('"') for c in line.split(sep)]
        if len(parts) < len(header):
            parts += [""] * (len(header) - len(parts))

        t = None
        dte = parse_date(parts[i_date]) if i_date is not None else None
        tme = parse_time(parts[i_time]) if i_time is not None else None
        if tme is not None:
            day = 0
            if dte is not None:
                if dte not in day_seen:
                    day_seen[dte] = len(day_seen)
                day = day_seen[dte] * 86400
            t = tme + day

        d = {}
        for c, k in zip(parts, cls):
            if k is None or k == "skip":
                continue
            v = fnum(c)
            if v is None:
                continue
            if isinstance(k, tuple):
                if 0 < v < 30:  # мс впрыска; мусор вида 318.64 отсеиваем
                    d["inj_max"] = max(d.get("inj_max") or 0, v)
            else:
                lim = LIMITS.get(k)
                if lim is not None and abs(v) > lim:
                    continue
                d[k] = v
        if t is not None:
            points.append((t, d))

    points.sort(key=lambda p: p[0])
    return points, tag, header


# ------------------------------------------------------------- анализ

def analyze(points, name, tag):
    out = []
    if len(points) < 10:
        out.append("Слишком мало строк ({}), пропускаю.".format(len(points)))
        return out

    ts = [t for t, _ in points]
    total = max(ts[-1] - ts[0], 1.0)

    out.append("Период: {} — {}  ({:.0f} мин, строк: {})".format(
        tstr(ts[0]), tstr(ts[-1]), total / 60.0, len(points)))

    def col(key):
        return [(t, d[key]) for t, d in points if d.get(key) is not None]

    def group(cond):
        res, cur = [], None
        for t, d in points:
            if cond(t, d):
                if cur is None:
                    cur = [t, t, [d]]
                else:
                    cur[1] = t
                    cur[2].append(d)
            elif cur is not None:
                res.append(cur)
                cur = None
        if cur is not None:
            res.append(cur)
        return res

    # --- температуры
    cl = [v for _, v in col("coolant")]
    ot = [v for _, v in col("oil_temp")]
    line = "ОЖ: " + ("{:.0f}…{:.0f} °C".format(min(cl), max(cl)) if cl else "н/д")
    line += "   Масло: " + ("{:.0f}…{:.0f} °C".format(min(ot), max(ot)) if ot else "н/д")
    out.append(line)

    # --- плотность записи (дырявость ELM)
    steps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    if len(steps) > 2:
        out.append("Запись: медианный шаг {:.1f} с, макс пауза {:.0f} с".format(
            med(steps), max(steps)))
        big = [(a, b) for a, b in zip(ts, ts[1:]) if b - a > 300]
        if big:
            out.append("Разрывы записи: " + "; ".join(
                "{} → {} ({:.1f} ч)".format(tstr(a), tstr(b), (b - a) / 3600.0)
                for a, b in big[:5]))

    # --- ХХ и MAP
    idle = []
    idle_ac = 0
    for t, d in points:
        rpm = d.get("rpm")
        sp = d.get("speed")
        if rpm is None or sp is None:
            continue
        pd = d.get("pedal")
        th = d.get("throttle")
        if sp == 0 and 650 <= rpm <= 1050 and (pd is None or pd < 5):
            if th is not None and th > 2.5:
                idle_ac += 1  # idle-up кондиционера — не ХХ для MAP
                continue
            idle.append((t, d))
    if idle_ac:
        out.append("ХХ: отсеяно {} точек idle-up кондиционера (дроссель >2.5%)".format(idle_ac))

    warm = [(t, d) for t, d in idle if (d.get("coolant") or 0) >= 60]
    cold = [(t, d) for t, d in idle if (d.get("coolant") or 0) < 60]

    for label, sel in (("прогретый", warm), ("холодный", cold)):
        vals = [d["map"] for _, d in sel if d.get("map") is not None]
        if len(vals) >= 20:
            out.append("MAP на ХХ ({}): мин {:.0f} / медиана {:.0f} / макс {:.0f} мбар ({} точек)".format(
                label, min(vals), med(vals), max(vals), len(vals)))

    # --- лямбды на ХХ (мВ; вольты конвертируем)
    o2_idle = [(t, d) for t, d in idle
               if d.get("o2_up") is not None and d.get("o2_down") is not None]
    if o2_idle:
        mx = max(max(d["o2_up"], d["o2_down"]) for _, d in o2_idle)
        scale = 1000.0 if mx <= 5.0 else 1.0
        up = [d["o2_up"] * scale for _, d in o2_idle]
        dn = [d["o2_down"] * scale for _, d in o2_idle]
        sync_lean = sum(1 for _, d in o2_idle
                        if d["o2_up"] * scale > 700 and d["o2_down"] * scale > 700)
        anti = sum(1 for _, d in o2_idle
                   if (d["o2_up"] * scale > 700 and d["o2_down"] * scale < 300)
                   or (d["o2_up"] * scale < 200 and d["o2_down"] * scale > 700))
        n = len(o2_idle)
        out.append("Лямбды на ХХ (мВ): верх {:.0f}…{:.0f} / низ {:.0f}…{:.0f} | "
                   "синхронно-бедные {:.0f}% | противофаза {:.0f}% ({} точек)".format(
            min(up), max(up), min(dn), max(dn),
            100.0 * sync_lean / n, 100.0 * anti / n, n))
        dn_st = [d["o2_down"] * scale for _, d in o2_idle]
        lean_dn = sum(1 for v in dn_st if v < 200)
        out.append("Нижняя лямбда на ХХ: медиана {:.0f} мВ, ниже 200 мВ в {:.0f}% точек".format(
            med(dn_st), 100.0 * lean_dn / len(dn_st)))
        wsel = [d for _, d in o2_idle if (d.get("coolant") or 0) >= 70]
        if wsel:
            dn_w = [d["o2_down"] * scale for d in wsel]
            lean_w = sum(1 for v in dn_w if v < 200)
            out.append("Нижняя лямбда на прогретом ХХ (ОЖ>=70): медиана {:.0f} мВ, "
                       "ниже 200 мВ в {:.0f}% точек ({} из {})".format(
                med(dn_w), 100.0 * lean_w / len(dn_w), lean_w, len(dn_w)))

    # --- коррекции смеси на ХХ
    upc = [d["up_corr"] for _, d in idle if d.get("up_corr") is not None]
    dnc = [d["down_corr"] for _, d in idle if d.get("down_corr") is not None]
    if upc or dnc:
        parts = []
        if upc:
            parts.append("верх медиана {:+.3f}".format(med(upc)))
        if dnc:
            parts.append("низ медиана {:+.3f}".format(med(dnc)))
        out.append("Коррекция смеси на ХХ: " + ", ".join(parts))

    # --- байпас (TurboBlowOff)
    byp = group(lambda t, d: (d.get("blowoff") is not None and d["blowoff"] >= 90))
    full = [g for g in byp if len(g[2]) >= 2]
    art = len(byp) - len(full)
    out.append("Байпас: {} полноценных событий ({} сэмплов-артефактов отсеяно):".format(
        len(full), art))
    for t0, t1, ds in full:
        out.append("  {} — {} | {:.0f}% | об {:.0f}→{:.0f} | газ {:.0f}→{:.0f} | "
                   "наддув {:.0f}→{:.0f} мбар".format(
            tstr(t0), tstr(t1),
            max(x["blowoff"] for x in ds),
            ds[0].get("rpm") or 0, ds[-1].get("rpm") or 0,
            ds[0].get("pedal") or 0, ds[-1].get("pedal") or 0,
            ds[0].get("turbo") or 0, ds[-1].get("turbo") or 0))

    br = group(lambda t, d: d.get("brake") == 1)
    brf = [g for g in br if len(g[2]) >= 2]
    if brf:
        out.append("Торможения: {} событий (сэмплов-артефактов {})".format(
            len(brf), len(br) - len(brf)))

    # --- недобор наддува при газе >=85%
    und = []
    for t, d in points:
        ti, tf, pd = d.get("turbo_instr"), d.get("turbo"), d.get("pedal")
        if ti is None or tf is None or pd is None:
            continue
        if pd >= 85 and ti - tf >= 200:
            und.append((t, d))
    if und:
        gr, cur = [], [und[0]]
        for item in und[1:]:
            if item[0] - cur[-1][0] <= 3:
                cur.append(item)
            else:
                gr.append(cur)
                cur = [item]
        gr.append(cur)
        out.append("Недобор наддува при газе >=85%: {} групп:".format(len(gr)))
        for g in gr:
            t0, t1 = g[0][0], g[-1][0]
            d0 = max(g, key=lambda x: x[1].get("turbo_instr", 0) - x[1].get("turbo", 0))
            diff = d0[1]["turbo_instr"] - d0[1]["turbo"]
            label = "СТОЙКИЙ" if (t1 - t0) >= 2 else "переходный"
            out.append("  {} | {:.0f} об/мин | зад {:.0f}, факт {:.0f} ({:+.0f}) | "
                       "дл {:.1f} с | {}".format(
                tstr(t0), d0[1].get("rpm") or 0, d0[1]["turbo_instr"],
                d0[1]["turbo"], diff, t1 - t0, label))

    # --- перелёты наддува
    ovs = []
    for t, d in points:
        ti, tf = d.get("turbo_instr"), d.get("turbo")
        if ti is None or tf is None:
            continue
        if tf - ti >= 400:
            ovs.append((t, d))
    if ovs:
        gr, cur = [], [ovs[0]]
        for item in ovs[1:]:
            if item[0] - cur[-1][0] <= 3:
                cur.append(item)
            else:
                gr.append(cur)
                cur = [item]
        gr.append(cur)
        mx = max(item[1]["turbo"] - item[1]["turbo_instr"] for item in ovs)
        out.append("Перелёты наддува на сбросе газа: {} групп, макс +{:.0f} мбар".format(
            len(gr), mx))

    # --- канал Errors: флаг ошибки в памяти, а не «активна сейчас»
    err_rows = [(t, d["err"]) for t, d in points if d.get("err") is not None]
    if err_rows:
        ones = sum(1 for _, v in err_rows if v >= 1)
        trans = sum(1 for a, b in zip(err_rows, err_rows[1:])
                    if (a[1] >= 1) != (b[1] >= 1))
        seg, start, prev_t = [], None, None
        for t, v in err_rows:
            if prev_t is not None and t - prev_t > 60:  # разрыв записи
                if start is not None:
                    seg.append((start, prev_t))
                start = None
            if v >= 1 and start is None:
                start = t
            if v < 1 and start is not None:
                seg.append((start, prev_t))
                start = None
            prev_t = t
        if start is not None:
            seg.append((start, prev_t))
        out.append("Флаг Errors: 1 в {} из {} строк ({:.0f}%), переключений {}".format(
            ones, len(err_rows), 100.0 * ones / len(err_rows), trans))
        for s0, s1 in seg[:12]:
            out.append("  {} — {} ({:.0f} с)".format(tstr(s0), tstr(s1), s1 - s0))

    # --- батарея
    batt_move = [d["battery"] for _, d in points
                 if d.get("battery") is not None and (d.get("speed") or 0) > 0]
    batt_rest = [d["battery"] for _, d in points
                 if d.get("battery") is not None and (d.get("speed") or 0) == 0]
    parts = []
    if batt_move:
        parts.append("движение мин {:.1f} В".format(min(batt_move)))
    if batt_rest:
        parts.append("зажигание/пуск мин {:.1f} В".format(min(batt_rest)))
    if parts:
        out.append("Батарея: " + " | ".join(parts))

    # --- детонация (нулевой порог = канал не читался)
    kn = [(t, d["knock"], d.get("knock_thr") or 0) for t, d in points
          if d.get("knock") is not None]
    if kn:
        line = "Детонация: макс сенсор {:.2f}".format(max(k[1] for k in kn))
        exc = [k for k in kn if k[2] > 0.1 and k[1] > k[2]]
        if exc:
            worst = max(exc, key=lambda k: k[1])
            line += " | превышений порога: {} точек, сильнейшее {:.2f} @ {}".format(
                len(exc), worst[1], tstr(worst[0]))
        out.append(line)

    # --- давление масла: только на прогретом масле
    mism = []
    for t, d in points:
        op, oi, otemp = d.get("oil_press"), d.get("oil_press_instr"), d.get("oil_temp")
        rpm = d.get("rpm")
        if rpm is None or rpm < 400:
            continue  # двигатель не работает — давление масла не сравниваем
        if op is None or oi is None or otemp is None:
            continue
        if otemp < 60:
            continue
        if op - oi < -300:
            mism.append((t, op - oi))
    if mism:
        diffs = [x for _, x in mism]
        tmax = max(mism, key=lambda p: abs(p[1]))[0]
        out.append("Давление масла (прогрето): недоборов факт<задание >300 мбар: {} "
                   "(медиана {:+.0f}, худший {:+.0f} @ {})".format(
            len(mism), med(diffs), min(diffs), tstr(tmax)))

    # --- ТНВД: рампа / задание / регулятор
    fp = [v for _, v in col("fuel_press")]
    fpi = [v for _, v in col("fuel_press_instr")]
    fpr = [v for _, v in col("fuel_press_reg")]
    if fp:
        line = "ТНВД: рампа {:.0f}…{:.0f} бар (медиана {:.0f})".format(
            min(fp), max(fp), med(fp))
        if fpi:
            line += " | задание {:.0f}…{:.0f} бар".format(min(fpi), max(fpi))
        out.append(line)
    if fpr:
        out.append("Регулятор ТНВД: {:.0f}…{:.0f}% (медиана {:.0f}%)".format(
            min(fpr), max(fpr), med(fpr)))

    # --- кондиционер
    acp = [v for _, v in col("ac_press")]
    if acp:
        on = [x for x in acp if x > 5.0]
        extra = (", компрессор включен в {} из {} точек".format(len(on), len(acp))
                 if on else "")
        out.append("Кондиционер: давление хладагента {:.1f}…{:.1f} бар{}".format(
            min(acp), max(acp), extra))

    # --- атмосфера
    atm = [v for _, v in col("atm")]
    if atm:
        out.append("Атмосфера: {:.0f} мбар (избыточный наддув = TurboPress минус атмосфера)".format(
            med(atm)))

    # --- доп. каналы
    extras = []
    ecu = [v for _, v in col("ecu_temp")]
    if ecu:
        extras.append("ЭБУ {:.0f}…{:.0f} °C".format(min(ecu), max(ecu)))
    am = [v for _, v in col("air_manifold")]
    if am:
        extras.append("AirManifold макс {:.0f}".format(max(am)))
    if extras:
        out.append("Доп.: " + ", ".join(extras))

    # --- максимумы
    rpm = [v for _, v in col("rpm")]
    air = [v for _, v in col("air")]
    inj = [v for _, v in col("inj_max")]
    parts = []
    if rpm:
        parts.append("обороты {:.0f}".format(max(rpm)))
    if air:
        parts.append("воздух {:.0f} кг/ч".format(max(air)))
    if inj:
        parts.append("впрыск {:.2f} мс".format(max(inj)))
    if parts:
        out.append("Максимумы: " + ", ".join(parts))

    return out


# ------------------------------------------------------------- запуск

def main():
    args = [a for a in sys.argv[1:] if a != "--no-sync"]
    if args:
        files = args
    else:
        files = sorted(glob.glob("MED17*.csv")) or sorted(glob.glob("*.csv"))
    if not files:
        print("CSV-файлы не найдены.")
        return
    out_all = []
    for path in files:
        points, tag, header = load_csv(path)
        out_all.append(SEP_LINE)
        out_all.append("Файл: {}{}".format(
            os.path.basename(path), "  [{}]".format(tag) if tag else ""))
        out_all.extend(analyze(points, path, tag))
    out_all.append("")
    text = "\n".join(out_all)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    sync_to_kb(OUT_FILE)


def sync_to_kb(report_path):
    """Влить свежий отчёт в базу знаний car_kb.json, если она рядом."""
    if "--no-sync" in sys.argv or not os.path.exists("car_kb.py"):
        return
    try:
        import car_kb
        car_kb.cmd_sync([report_path])
    except Exception as e:
        print("(car_kb sync пропущен: {})".format(e))


if __name__ == "__main__":
    main()
