# ============================================================
# car_core.py — шаг 1: загрузка, фильтры, режимы, поездки
# Границы записи по портрету глушения (Speed=0, Gear=P, обрыв записи).
# Паузы: SHUTDOWN рвёт поездку, LINK_LOSS — нет. Атрибуция интервалов
# — к строке ДО паузы; OFF-карман для хвоста файла.
# Запуск: python car_core.py [папка]  (по умолчанию '.')
# ============================================================
import os, sys, glob
import pandas as pd
import numpy as np


def load_csv(path):
    df = pd.read_csv(path, sep=';', encoding='utf-8', low_memory=False)
    ts = pd.to_datetime(df['Date'] + ' ' + df['Time'], format='%Y.%m.%d %H:%M:%S.%f')
    df.insert(0, 'ts', ts)
    for c in df.columns:
        if c in ('Date', 'Time', 'ts', 'Gear'): continue
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.sort_values('ts').reset_index(drop=True)


def mark_glitches(df):
    """Помечаем брак каналов, не удаляем: физика vs дефект записи."""
    bad = pd.Series(False, index=df.index)
    for c in df.columns:
        if c.startswith('Inj.') and 'Time' in c:
            bad |= ((df[c] > 15) & (df['Revs'] > 1000)).fillna(False)
    bad |= (df['FuelPressReg'] > 110).fillna(False)
    df['glitch'] = bad
    return df


def phantom_mask(df):
    """Фантом в паузах: Revs~ХХ, Inj=0, лямбды на холодном дефолте
    (446 мВ, нагрев 0). Не путать с честным fuel cut: там нагрев активен."""
    ph = (df['Revs'].between(600, 900)) & (df['Inj.1Time'].fillna(0) == 0) \
         & (df['UpO2Volt'] >= 440) & (df['UpO2Heat'].fillna(0) == 0) \
         & (df['DownO2Volt'] >= 440) & (df['DownO2Heat'].fillna(0) == 0)
    return ph.fillna(False)


def running_mask(df):
    inj = df[['Inj.1Time', 'Inj.2Time', 'Inj.3Time', 'Inj.4Time']].fillna(0).max(axis=1)
    heat = df[['UpO2Heat', 'DownO2Heat']].fillna(0).max(axis=1)
    return ((inj > 0) | (heat > 0)) & ~phantom_mask(df)


def pause_types(df):
    """Разрыв записи = dt > 60 с. SHUTDOWN: по обе стороны Speed=0 и
    Gear P/N (портрет глушения). Иначе LINK_LOSS — поездка не рвётся."""
    dt = df['ts'].diff().dt.total_seconds()
    out = []
    for i in np.where(dt > 60)[0]:
        prev, nxt = i - 1, i
        sp = (df['Speed'].iloc[prev] == 0) and (df['Speed'].iloc[nxt] == 0)
        gr = str(df['Gear'].iloc[prev]).strip().upper() in ('P', 'N') and \
             str(df['Gear'].iloc[nxt]).strip().upper() in ('P', 'N')
        out.append((int(i), 'SHUTDOWN' if (sp and gr) else 'LINK_LOSS'))
    return out


def segment(df, run_col):
    """Поездки рвутся ТОЛЬКО на SHUTDOWN-паузах. Сегменты — интервалы
    между соседними SHUTDOWN. Хвост файла без глушения = поездка [EOF]
    + виртуальный OFF-карман."""
    df['dt_s'] = df['ts'].diff().dt.total_seconds().fillna(0)
    gaps = dict(pause_types(df))
    for i in gaps:                       # dt строки после паузы обнуляем
        df.loc[i, 'dt_s'] = 0.0          # (иначе пауза прилипает к первой строке)
    shutdowns = sorted(i for i, t in gaps.items() if t == 'SHUTDOWN')
    bounds = [0] + shutdowns + [len(df)]
    running = df[run_col]
    trips = []
    for k in range(len(bounds) - 1):
        s = bounds[k] + (1 if k > 0 else 0)
        e = bounds[k + 1] - 1 if k + 1 < len(bounds) - 1 else len(df) - 1
        if e < s: continue
        ridx = df.index[(df.index >= s) & (df.index <= e) & df[run_col]]
        if len(ridx) == 0: continue      # стоянка с зажиганием — не поездка
        kind = 'SHUTDOWN' if k < len(bounds) - 2 else 'EOF'
        trips.append((ridx[0], ridx[-1], kind))
    return trips, running


def classify_modes(df, run_col):
    rev, spd = df['Revs'].fillna(0), df['Speed'].fillna(0)
    thr, ped = df['ThrottleAngle'].fillna(0), df['AccelPedalPos'].fillna(0)
    cool = df['Coolant'].fillna(99)
    run = df[run_col]
    mode = pd.Series('OTHER', index=df.index)
    mode[~run] = 'OFF'
    m = run & (rev >= 200) & (rev <= 900) & (spd == 0) & (thr >= 30)
    mode[m & (mode == 'OTHER')] = 'CRANK'
    m = run & (cool < 60)
    mode[m & (mode == 'OTHER')] = 'WARMUP'
    m = run & (spd == 0) & (ped <= 6) & rev.between(650, 950) & cool.between(60, 75)
    mode[m & (mode == 'OTHER')] = 'IDLE_COLD'
    m = run & (spd == 0) & (ped <= 6) & rev.between(650, 950) & (cool >= 75)
    mode[m & (mode == 'OTHER')] = 'IDLE_WARM'
    m = run & (ped >= 85)
    mode[m & (mode == 'OTHER')] = 'FULL_LOAD'
    m = run & (rev >= 1500) & (thr >= 20)
    mode[m & (mode == 'OTHER')] = 'LOAD'
    m = run & (thr >= 8)
    mode[m & (mode == 'OTHER')] = 'PART_LOAD'
    m = run & (spd >= 20) & (ped <= 2) & (rev > 1200)
    mode[m & (mode == 'OTHER')] = 'COAST'
    m = run & (spd >= 30) & (ped < 5)
    mode[m & (mode == 'OTHER')] = 'CRUISE'
    m = run & (spd > 0)
    mode[m & (mode == 'OTHER')] = 'DRIVE_LOW'
    df['STABLE'] = (df['Revs'].diff().abs() <= 30).fillna(False) & run
    df['ARMED'] = df['KnockSensorThr'].fillna(0) > 0
    df['mode'] = mode
    return df


def trip_descriptors(df, trips):
    out = []
    for n, (s, e, kind) in enumerate(trips, 1):
        seg = df.loc[s:e]
        dtc = seg['dt_s'].clip(upper=120)      # защита от stray-гэпов
        dur = dtc.sum() / 60
        dist = (seg['Speed'] * dtc).sum() / 3600
        stops = int(((seg['Speed'] > 0).astype(int).diff().fillna(0) == -1).sum())
        vc = seg['mode'].value_counts(normalize=True) * 100
        prof = ', '.join(f'{m} {p:.0f}%' for m, p in vc.items() if p >= 3)
        out.append(dict(n=n, t0=seg['ts'].iloc[0], t1=seg['ts'].iloc[-1],
                        dur=dur, dist=dist, vmax=seg['Speed'].max(),
                        cool0=seg['Coolant'].iloc[0], cool1=seg['Coolant'].iloc[-1],
                        stops=stops, kind=kind, prof=prof))
    return out


def fmt_t(ts): return ts.strftime('%H:%M:%S')


def report_file(path):
    df = load_csv(path)
    df = mark_glitches(df)
    df['running'] = running_mask(df)
    trips, _ = segment(df, 'running')
    df = classify_modes(df, 'running')
    descs = trip_descriptors(df, trips)
    span = (df['ts'].iloc[-1] - df['ts'].iloc[0]).total_seconds() / 60
    rec = df['dt_s'].clip(upper=120).sum() / 60
    n_link = sum(1 for _, t in pause_types(df) if t == 'LINK_LOSS')
    print(f'\n=== {os.path.basename(path)}: {df["ts"].iloc[0]} — {df["ts"].iloc[-1]} ===')
    print(f'Строк {len(df)}; записи {rec:.1f} мин, паузы {span - rec:.1f} мин '
          f'(разрывов связи: {n_link}); баланс {rec + (span - rec):.1f} мин')
    for d in descs:
        print(f'Поездка {d["n"]}: {fmt_t(d["t0"])}–{fmt_t(d["t1"])}  '
              f'{d["dur"]:.1f} мин, {d["dist"]:.1f} км, макс {d["vmax"]:.0f} км/ч, '
              f'ОЖ {d["cool0"]:.0f}→{d["cool1"]:.0f}°C, остановок {d["stops"]} [{d["kind"]}]')
        print(f'    профиль: {d["prof"]}')
    return df, descs


def main(folder='.'):
    files = sorted(glob.glob(os.path.join(folder, 'MED17*.csv')))
    if not files:
        print('MED17*.csv не найдены в', folder); return
    for f in files:
        try:
            report_file(f)
        except Exception as ex:
            print(f'ОШИБКА {f}: {ex}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
