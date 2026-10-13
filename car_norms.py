#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
car_norms.py v3.3 — сверка логов FAP (MED17.4.2, EP6 THP) с нормами PSA-практики.

ИСТОЧНИКИ НОРМ:
 [UD] drive2.ru/l/684250001416662427 — "Диагностика и снятие логов EP6. Ч.3. Турбо" (UltraDed):
      MAP ХХ прогретый без нагрузок 280-330 идеал; OilPumpValve ХХ 90-99% идеал, <70% плохо
      (масло утекает: шейки РВ, коленвал, фильтр); OilPress = манометр +500 мбар;
      FuelPress (ТНВД) >=40 бар, 20-30 насос стареет, 5-20 труп; FuelPressReg ХХ 13-29%, макс <60%;
      UpO2Volt 100-850 мВ без зависаний; AdvCorr: идеал 0, допуск -3, -6 плохо, -9 беда, -12 предел;
      TurboPress: 1000 = атмосфера, сток надувает до 1600-1700
 [EM] euromotor-guide: давление масла EP6 ХХ горячий мин 0.8-1.0 бар; места подсоса P2279
 [AP] autoprogs.org разбор P2279 на EP6: триггер = MAP выше задания при данном дросселе
 [CS] c4-sedan: THP ХХ горячий 2.7-2.9 бар
 [HD] здоровые дни наблюдения 05-09.10: MAP ХХ 370-390, нижняя лямбда 420-460 мВ
 [PR] общая практика: ОЖ 85-95; батарея в движении >=13.0; прокрутка >=10.0; впрыск <10 мс
 [KB] база знаний проекта: нормы, уточнённые по нашим логам (car_kb.py)

ЧТО НОВОГО В v3.1 (правки после ревизии):
 - детонация: превышения считаются только при работающем впрыске (Inj.1Time > 0.5 мс)
   и ненулевом пороге — пусковые всплески и отсечка топлива не портят счёт;
 - недобор масла: только прогретое масло (>=60 C), обороты >700 и задание >800 мбар;
 - ТНВД: статистика только по движению с реальным впрыском (Inj.1Time > 2 мс),
   отсечка топлива (впрыск ~0 при качении) исключена из медиан и долей;
 - впрыск: единичные пики >15 мс отбрасываются как глитчи записи;
 - лямбды на ХХ: считаются тоже только с впрыском (без отсечки на ХХ).

ЧТО НОВОГО В v3.2:
 - поиск логов перенесён в car_common (папка raw рядом со скриптом);
 - OilPumpValve ХХ: норма зависит от OilTemp (55-97% по зонам), норма [UD] снята;
 - флаг утечки давления масла = OPV>90% при OilPress<2200 мбар на горячем ХХ.


 ЧТО НОВОГО В v3.3:
 - детонация: нормирована на 1000 активных точек (счётчик зависел от длины лога);
 - FuelPressReg макс: значения >=99 отбрасываются как насыщение записи.
"""

import os, re, statistics as st, sys
from car_common import find_csvs

# ------------------------------------------------------------ утилиты

def fnum(x):
    if x is None:
        return None
    s = str(x).strip().replace(',', '.')
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return None if v != v else v   # nan -> None

def load_csv(path):
    lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    hdr, rows = None, []
    dr = re.compile(r'^\d{4}\.\d{2}\.\d{2}')
    for ln in lines:
        p = ln.split(';')
        if len(p) < 40:
            continue
        if p[0].strip().lower().startswith('date'):
            hdr = [x.strip() for x in p]
            continue
        if hdr and dr.match(p[0].strip()):
            rows.append(p)
    return hdr, rows

def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None

def share(vals, pred):
    vals = [x for x in vals if x is not None]
    if not vals:
        return None
    return sum(1 for x in vals if pred(x)) / len(vals) * 100

def dn(ok, grey, val):   # меньше — лучше
    if val <= ok:   return '[ok]'
    if val <= grey: return '[~]'
    return '[!!]'

def up(ok, grey, val):   # больше — лучше
    if val >= ok:   return '[ok]'
    if val >= grey: return '[~]'
    return '[!!]'

def band(lo, hi, val, glo, ghi):   # окно нормы
    if lo <= val <= hi:  return '[ok]'
    if glo <= val <= ghi: return '[~]'
    return '[!!]'

# ------------------------------------------------------------ анализ

NEEDED = ['Time', 'Revs', 'Coolant', 'OilTemp', 'ThrottleAngle', 'Speed',
          'IntakeAirPress', 'IntakeAirPressInstr', 'DownO2Volt', 'UpO2Volt',
          'UpMixCorr', 'OilPress', 'OilPressInstr', 'OilPumpValve',
          'FuelPress', 'FuelPressReg', 'Battery', 'Inj.1Time', 'KnockSensor',
          'KnockSensorThr', 'Errors', 'TurboPress', 'TurboInstr', 'AccelPedalPos',
          'Cyl.1AdvCorr', 'Cyl.2AdvCorr', 'Cyl.3AdvCorr', 'Cyl.4AdvCorr']

def analyze(path):
    hdr, rows = load_csv(path)
    print('=' * 72)
    print('Файл: {}'.format(os.path.basename(path)))
    if not hdr or not rows:
        print('  [!!] файл не разобран (строк данных: {})'.format(len(rows)))
        return 1

    idx = {n: hdr.index(n) for n in NEEDED if n in hdr}
    tidx = hdr.index('Time') if 'Time' in hdr else None
    def col(n):
        i = idx.get(n)
        return [fnum(r[i]) if i is not None and i < len(r) else None for r in rows]
    C = {n: col(n) for n in NEEDED}

    R, CO, TH, SP = C['Revs'], C['Coolant'], C['ThrottleAngle'], C['Speed']
    INJ = C['Inj.1Time']
    inj_on = lambda i: INJ[i] is not None and INJ[i] > 0.5

    def mask(fn):
        return [i for i in range(len(rows))
                if None not in (R[i], CO[i], TH[i], SP[i]) and fn(i)]
    idle = mask(lambda i: 650 <= R[i] <= 900 and CO[i] >= 70 and TH[i] <= 2.5
                and SP[i] == 0 and inj_on(i))
    moving = mask(lambda i: SP[i] > 5 and INJ[i] is not None and INJ[i] > 2)
    moving_hi = mask(lambda i: SP[i] > 5 and INJ[i] is not None and INJ[i] > 2
                     and TH[i] >= 20)   # реальная нагрузка: без накатов и отсечки

    n_warn = [0]
    def out(lbl, val, unit, tag, msg, src):
        if val is None or tag is None:
            print('  [--] {}: нет данных'.format(lbl))
            return
        if tag == '[!!]':
            n_warn[0] += 1
        print('  {} {}: {}{}  ({})  [{}]'.format(tag, lbl, val, unit, msg, src))

    print('  точек ХХ (прогрет, без AC, с впрыском): {} | в движении: {}'.format(
        len(idle), len(moving)))

    # --- ХХ: MAP ---
    m = med([C['IntakeAirPress'][i] for i in idle])
    if m is not None:
        out('MAP ХХ', '{:.0f}'.format(m), ' мбар',
            dn(400, 430, m), 'норма (идеал по UD 280-330)', 'UD+HD')
    ex = med([C['IntakeAirPress'][i] - C['IntakeAirPressInstr'][i] for i in idle
              if C['IntakeAirPressInstr'][i] is not None])
    if ex is not None:
        out('MAP минус задание ХХ', '{:+.0f}'.format(ex), ' мбар',
            dn(20, 40, ex), 'соответствие модели (триггер P2279 — превышение)', 'AP')

    # --- ХХ: лямбды ---
    dv = [C['DownO2Volt'][i] for i in idle if C['DownO2Volt'][i] is not None]
    if dv:
        m = med(dv)
        out('лямбда низ ХХ медиана', '{:.0f}'.format(m), ' мВ',
            band(420, 460, m, 380, 500), 'стехиометрия', 'HD')
        sh = share(dv, lambda x: x < 200)
        out('лямбда низ: доля <200 мВ', '{:.0f}'.format(sh), ' %',
            dn(10, 30, sh), 'стойко бедно при высоком', 'HD')
    uv = [C['UpO2Volt'][i] for i in idle if C['UpO2Volt'][i] is not None]
    if uv:
        bins = {}
        for x in uv:
            b = int(x // 50) * 50
            bins[b] = bins.get(b, 0) + 1
        b, cnt = max(bins.items(), key=lambda kv: kv[1])
        dom = cnt / len(uv) * 100
        out('лямбда верх: доминирующий бин', '{}-{} мВ, {:.0f}%'.format(b, b + 50, dom),
            '', dn(40, 60, dom), 'зависание, если один бин съел всё', 'UD')
        m = med(uv)
        out('лямбда верх ХХ медиана', '{:.0f}'.format(m), ' мВ',
            band(650, 790, m, 600, 820),
            'по нашим дням 691-754 — стабильно, норма UD неприменима', 'KB')

    um = med([C['UpMixCorr'][i] for i in idle if C['UpMixCorr'][i] is not None])
    if um is not None:
        out('коррекция смеси ХХ (верх)', '{:+.1f}'.format(um), ' %',
            band(-4, 4, um, -8, 8), 'ЭБУ компенсирует — сенсор/смесь в норме', 'UD')

    # --- масло ---
    opv_idle = [(C['OilPumpValve'][i], C['OilTemp'][i]) for i in idle
                if C['OilPumpValve'][i] is not None and C['OilTemp'][i] is not None]
    if opv_idle:
        tmed = med([t for _, t in opv_idle])
        m = med([v for v, _ in opv_idle])
        zones = [(0, 40, 55, 70), (40, 60, 60, 80), (60, 75, 70, 94), (75, 200, 75, 97)]
        tlo, thi, lo, hi = next((a, b, c, d) for a, b, c, d in zones
                                if a <= (tmed or 0) < b)
        out('OilPumpValve ХХ (масло {:.0f} C)'.format(tmed or 0), '{:.0f}'.format(m), ' %',
            band(lo, hi, m, lo - 10, hi + 2),
            'норма по OilTemp: <40C 55-70; 40-60 60-80; 60-75 70-94; 75+ 75-97 '
            '(corr OPV~OilTemp 0.73-0.78, дни 06/13.10)', 'KB')
        leak = [i for i in idle
                if C['OilPumpValve'][i] is not None and C['OilPumpValve'][i] > 90
                and C['OilPress'][i] is not None and C['OilPress'][i] < 2200
                and C['OilTemp'][i] is not None and C['OilTemp'][i] >= 75]
        if leak:
            out('утечка давления масла (OPV>90% при <2200 мбар)',
                '{} точек на горячем ХХ'.format(len(leak)), '',
                dn(2, 5, len(leak)),
                'насос давит на максимуме, давление не растёт — реальный флаг утечки', 'KB')
    m = med([C['OilPress'][i] for i in idle if C['OilPress'][i] is not None])
    if m is not None:
        out('давление масла ХХ', '{:.0f}'.format(m), ' мбар',
            up(2000, 1200, m), 'мин 0.8-1.0 бар; THP обычно 2.7-2.9', 'EM+CS')
    cand = [i for i in range(len(rows))
            if C['OilTemp'][i] is not None and C['OilTemp'][i] >= 60
            and R[i] is not None and R[i] > 700
            and C['OilPressInstr'][i] is not None and C['OilPressInstr'][i] > 800
            and C['OilPress'][i] is not None]
    deficits = [C['OilPress'][i] - C['OilPressInstr'][i] for i in cand]
    bad = [d for d in deficits if d < -300]
    if deficits:
        out('недобор масла (warm, об>700, зад>800)',
            '{} точек, медиана {:+.0f}'.format(len(bad), med(bad) if bad else 0.0), ' мбар',
            dn(50, 300, len(bad)),
            'расхождение факт/задание в нагрузке', 'UD')

    # --- ТНВД (только реальная нагрузка: дроссель >=20%) ---
    if moving_hi:
        fp = [C['FuelPress'][i] for i in moving_hi if C['FuelPress'][i] is not None]
        if fp:
            m = med(fp)
            out('ТНВД в движении (с впрыском)', '{:.0f}'.format(m), ' бар',
                up(40, 30, m), '>=40 норма; 20-30 стареет', 'UD')
            sh = share(fp, lambda x: x < 30)
            out('ТНВД: доля <30 бар', '{:.2f}'.format(sh), ' %',
                dn(1, 5, sh), 'просадки ниже 30 — только на отсечке', 'UD')
        m = med([C['FuelPressReg'][i] for i in idle if C['FuelPressReg'][i] is not None])
        if m is not None:
            out('FuelPressReg ХХ', '{:.0f}'.format(m), ' %',
                band(38, 50, m, 32, 55), 'ХХ (перекалибровано по 05-11.10)', 'KB')
        mx = [C['FuelPressReg'][i] for i in range(len(rows))
              if C['FuelPressReg'][i] is not None and C['FuelPressReg'][i] < 99]
        if mx:
            out('FuelPressReg макс', '{:.0f}'.format(max(mx)), ' %',
                dn(56, 65, max(mx)), 'макс до ~56%, разовые 57-65 — под наблюдением', 'KB')

    # --- зажигание и детонация (только с впрыском и порогом >0) ---
    kpts = [i for i in range(len(rows))
            if inj_on(i) and C['KnockSensorThr'][i] is not None
            and C['KnockSensorThr'][i] > 0
            and C['KnockSensor'][i] is not None]
    kover = [i for i in kpts if C['KnockSensor'][i] > C['KnockSensorThr'][i]]
    if kpts:
        rate = len(kover) / len(kpts) * 1000
        out('детонация: превышений на 1000 точек', '{:.2f}'.format(rate), '',
            dn(2.0, 4.0, rate),
            'превышения маргинальные (сенсор 3.8-7.5 при пороге 2.6-2.9)', 'KB')
        if kover:
            print('     детонация: {} из {} точек, макс сенсор {:.1f} мВ (при пороге {:.1f})'.format(
                len(kover), len(kpts),
                max(C['KnockSensor'][i] for i in kover),
                max(C['KnockSensorThr'][i] for i in kover)))
    adv = [C['Cyl.{}AdvCorr'.format(k)][i] for k in (1, 2, 3, 4)
           for i in moving if C['Cyl.{}AdvCorr'.format(k)][i] is not None]
    if adv:
        s3 = share(adv, lambda x: x <= -3)
        s6 = share(adv, lambda x: x <= -6)
        s9 = share(adv, lambda x: x <= -9)
        print('  [--] откаты (фон): <=-3 гр {:.1f}%, <=-6 гр {:.1f}% — норма для этой машины, не флаг'.format(s3, s6))
        out('откаты: доля <=-9 гр', '{:.2f}'.format(s9), ' %',
            dn(8, 12, s9),
            'калибровка 05-13.10: здоровые дни 1.5-6.6%, проблемные 0.9-1.2% — фон, не диагноз', 'KB')

    # --- батарея и прочее ---
    bm = [C['Battery'][i] for i in range(len(rows))
          if SP[i] is not None and SP[i] > 20 and inj_on(i) and C['Battery'][i] is not None]
    if bm:
        bmin = min(bm)
        out('батарея в движении мин (>20 км/ч)', '{:.1f}'.format(bmin), ' В',
            up(13.0, 12.5, bmin), 'в движении >=13.0', 'PR')
        if bmin < 12.5:
            idxs_b = [i for i in range(len(rows))
                      if C['Battery'][i] is not None and C['Battery'][i] <= bmin + 0.3
                      and SP[i] is not None and SP[i] > 20 and inj_on(i)][:3]
            for i in idxs_b:
                t_s = rows[i][tidx].strip() if tidx is not None and tidx < len(rows[i]) else '?'
                print('     провал: {} | {:.1f} В | {} об/мин | газ {:.0f}% | Errors={}'.format(
                    t_s, C['Battery'][i], R[i] or 0, C['AccelPedalPos'][i] or 0,
                    C['Errors'][i] if C['Errors'][i] is not None else '?'))
    co = [x for x in CO if x is not None]
    if co:
        out('ОЖ макс', '{:.0f}'.format(max(co)), ' C',
            dn(95, 105, max(co)), 'норма 85-95', 'PR')
    gl = [INJ[i] for i in range(len(rows)) if INJ[i] is not None and INJ[i] > 15]
    if gl:
        print('  глитчей впрыска >15 мс отброшено из статистики: {}'.format(len(gl)))
    inj = [INJ[i] for i in range(len(rows)) if inj_on(i) and INJ[i] <= 15]
    if inj:
        out('впрыск макс (без глитчей)', '{:.1f}'.format(max(inj)), ' мс',
            dn(10, 15, max(inj)), '<10 мс на полную', 'PR')

    # --- наддув ---
    idxs = [i for i in range(len(rows))
            if SP[i] is not None and SP[i] > 5
            and C['AccelPedalPos'][i] is not None and C['AccelPedalPos'][i] >= 85
            and C['TurboInstr'][i] is not None and C['TurboPress'][i] is not None
            and C['TurboInstr'][i] - C['TurboPress'][i] > 200]
    groups = []
    for i in idxs:
        if groups and i - groups[-1][-1] <= 2:
            groups[-1].append(i)
        else:
            groups.append([i])
    stable = [g_ for g_ in groups if R[g_[0]] is not None and R[g_[0]] >= 2500]
    if groups:
        print('  недобор наддува при газе >=85%: {} групп, из них стойких (об>=2500): {}'.format(
            len(groups), len(stable)))
        for g_ in stable[:5]:
            i0 = g_[0]
            print('    {} | {} об/мин | зад {:.0f}, факт {:.0f} (+{:.0f}) | дл {:.1f} с'.format(
                rows[i0][tidx].strip() if tidx is not None and tidx < len(rows[i0]) else '?',
                R[i0], C['TurboInstr'][i0], C['TurboPress'][i0],
                C['TurboInstr'][i0] - C['TurboPress'][i0], (g_[-1] - g_[0]) * 0.5))
        if len(stable) > 2:
            n_warn[0] += len(stable) - 2

    # --- Errors ---
    ev = [C['Errors'][i] for i in range(len(rows))]
    if any(x is not None for x in ev):
        p1 = sum(1 for x in ev if x == 1)
        trans = sum(1 for i in range(1, len(ev))
                    if ev[i] != ev[i - 1] and None not in (ev[i], ev[i - 1]))
        print('  Флаг Errors: 1 в {} из {} строк ({}%), переключений {}'.format(
            p1, len(ev), round(p1 / len(ev) * 100), trans))

    print('  ---')
    print('  Итого предупреждений [!!]: {}'.format(n_warn[0]))
    return n_warn[0]

def main():
    files = find_csvs(sys.argv[1:])
    if not files:
        return
    tot = 0
    for f in files:
        tot += analyze(f)
    print()
    print('Всего предупреждений по файлам: {}'.format(tot))

if __name__ == '__main__':
    main()
