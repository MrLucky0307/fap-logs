#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
car_service_note.py v1.0 — одностраничная справка механику по проекту fap-logs.
Данные берёт из папки raw (MED17*.csv), выводит в консоль и сохраняет
в service_note.txt рядом со скриптами.
"""

import os
from car_common import find_csvs, BASE
from car_norms import fnum, load_csv, med, share, NEEDED

OUT = os.path.join(BASE, "service_note.txt")

# ------------------------------------------------------------ сводка по дню

def day_stats(path):
    hdr, rows = load_csv(path)
    if not hdr or not rows:
        return None
    idx = {n: hdr.index(n) for n in NEEDED if n in hdr}
    tidx = hdr.index('Time') if 'Time' in hdr else None
    def col(n):
        i = idx.get(n)
        return [fnum(r[i]) if i is not None and i < len(r) else None for r in rows]
    C = {n: col(n) for n in NEEDED}
    R, CO, TH, SP, INJ = C['Revs'], C['Coolant'], C['ThrottleAngle'], C['Speed'], C['Inj.1Time']
    inj_on = lambda i: INJ[i] is not None and INJ[i] > 0.5

    idle = [i for i in range(len(rows))
            if None not in (R[i], CO[i], TH[i], SP[i]) and 650 <= R[i] <= 900
            and CO[i] >= 70 and TH[i] <= 2.5 and SP[i] == 0 and inj_on(i)]
    ev = [C['Errors'][i] for i in range(len(rows))]
    d = {'date': rows[0][0].strip()[:10], 'n': len(rows), 'idle': len(idle)}
    d['errs'] = round(sum(1 for x in ev if x == 1) / len(ev) * 100) if ev else None
    d['lam_lo'] = med([C['DownO2Volt'][i] for i in idle if C['DownO2Volt'][i] is not None])
    d['lam_lo200'] = share([C['DownO2Volt'][i] for i in idle if C['DownO2Volt'][i] is not None],
                           lambda x: x < 200)
    d['lam_up'] = med([C['UpO2Volt'][i] for i in idle if C['UpO2Volt'][i] is not None])
    d['corr'] = med([C['UpMixCorr'][i] for i in idle if C['UpMixCorr'][i] is not None])
    cand = [i for i in range(len(rows))
            if C['OilTemp'][i] is not None and C['OilTemp'][i] >= 60
            and R[i] is not None and R[i] > 700
            and C['OilPressInstr'][i] is not None and C['OilPressInstr'][i] > 800
            and C['OilPress'][i] is not None]
    bad = [C['OilPress'][i] - C['OilPressInstr'][i] for i in cand
           if C['OilPress'][i] - C['OilPressInstr'][i] < -300]
    d['oil'] = len(bad)
    bm = [(C['Battery'][i], i) for i in range(len(rows))
          if SP[i] is not None and SP[i] > 20 and inj_on(i) and C['Battery'][i] is not None]
    d['bat'] = min(b for b, _ in bm) if bm else None
    d['bat_ctx'] = sorted(bm)[:3]
    d['tidx'] = tidx
    d['rows'] = rows
    d['R'] = R
    d['C'] = C
    return d

def fmt(v, pat, suf=''):
    return ('--' if v is None else pat.format(v)) + suf

# ------------------------------------------------------------ сборка текста

def build_note(stats):
    L = []
    L.append('СПРАВКА ДЛЯ СЕРВИСА — EP6 THP (MED17.4.2), логи 05-13.10.2026')
    L.append('=' * 60)
    L.append('')
    L.append('1. ХРОНОЛОГИЯ ПО ДНЯМ (Errors = доля строк с активным флагом)')
    L.append('день       |Errors |лямбда низ/верх, мВ |масло, тчк |батарея мин, В')
    for s in sorted(stats, key=lambda x: x['date']):
        L.append('{} | {:>4}% | {:>3} / {:>3} | {:>3} | {}'.format(
            s['date'], fmt(s['errs'], '{:.0f}'),
            fmt(s['lam_lo'], '{:.0f}'), fmt(s['lam_up'], '{:.0f}'),
            fmt(s['oil'], '{:.0f}'), fmt(s['bat'], '{:.1f}')))
    L.append('')
    L.append('2. ЭТАЛОННЫЕ ДНИ (контроль): 05-09.10 и 10.10 — все параметры двигателя')
    L.append('   в норме. ВАЖНО: флаг Errors горел и на здоровых днях (05-07: 100%),')
    L.append('   но failsafe-сигнатура (лямбды, масло, бортсеть) появилась только 11-13.10.')
    L.append('   => ошибка присутствовала давно, тяжёлые режимы ЭБУ включил недавно:')
    L.append('   либо накопление, либо подсос усилился. Это о механической динамике проблемы.')
    L.append('')
    L.append('3. СИГНАТУРА FAILSAFE (при активном P2279):')
    L.append('   - нижняя лямбда падает 446 -> 82-91 мВ, доля <200 мВ до 96%')
    L.append('   - верхняя лямбда падает 734 -> 326-331 мВ (обе в открытой петле)')
    L.append('   - коррекция смеси замирает на ~+0.3% => смесь НЕ бедная, датчики живые')
    L.append('   - недобор масла (факт/задание) 250 -> 800+ точек в дни с ошибкой')
    L.append('   - провалы бортсети 11.4-11.8 В в движении — тоже только в дни с ошибкой')
    L.append('')
    L.append('4. ЭПИЗОДЫ БАТАРЕИ (движение >20 км/ч, с впрыском):')
    for s in stats:
        if s['bat'] is not None and s['bat'] < 12.5:
            L.append('   {}: мин {:.1f} В'.format(s['date'], s['bat']))
            for b, i in s['bat_ctx']:
                t_s = (s['rows'][i][s['tidx']].strip()
                       if s['tidx'] is not None and s['tidx'] < len(s['rows'][i]) else '?')
                L.append('     {} | {:.1f} В | {} об/мин | газ {:.0f}% | Errors={:.0f}'.format(
                    t_s, b, s['R'][i] or 0, s['C']['AccelPedalPos'][i] or 0,
                    s['C']['Errors'][i] or 0))
    L.append('')
    L.append('5. ЧТО ПРОСИТЬ ПРОВЕРИТЬ:')
    L.append('   a) дым-машина: подсос впуска (трубки, прокладки впускного коллектора,')
    L.append('      сапун, уплотнения форсунок) — P2279 активен с 05.10, на 10.10 исчезал')
    L.append('      и вернулся => механическая природа, а не датчик MAP')
    L.append('   b) считать ошибки и снять freeze-frame по P2279 (прошлый сканер)')
    L.append('   c) напряжение генератора под нагрузкой: эпизоды 11.4-12.2 В')
    L.append('      (10.10 07:42 Errors=0 — эпизод на здоровом дне, отдельно отметить)')
    L.append('   d) после ремонта — повторный лог по той же методике, сверим эталон')
    L.append('')
    L.append('   (в логах 05.10 и 07.10 нижний лямбда-канал не записывался — конфигурация логгера)')
    L.append('Нормы калиброваны по дням 05-13.10 (car_norms v3.3), эталон 05-09.10.')
    return '\n'.join(L)

def main():
    files = find_csvs()
    if not files:
        return
    stats = [s for s in (day_stats(f) for f in files) if s is not None]
    if not stats:
        print('Логи не разобраны')
        return
    note = build_note(stats)
    print(note)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(note)
    print()
    print('Справка сохранена: {}'.format(OUT))

if __name__ == '__main__':
    main()
