# ================= АДДОН: форсунки, VVT, детонация, fuel cut =================
# Вставить в car_norms.py рядом с существующими проверками.
# Зависимости: pandas as pd, numpy as np.
# Вызов для каждого MED17-файла:  run_engine_tests(df)  ->  список строк [ok]/[~]/[!!]

import numpy as np
import pandas as pd

INJ_COLS = ['Inj.1Time', 'Inj.2Time', 'Inj.3Time', 'Inj.4Time']

def _num(df, col):
    return pd.to_numeric(df[col], errors='coerce')

def build_modes(df):
    """Маски режимов с фильтрацией переходных процессов."""
    inj_mean = df[INJ_COLS].mean(axis=1)
    running = inj_mean > 0.2                       # двигатель работает (есть впрыск)
    warm = df['Coolant'] >= 60                     # прогрет
    d_rpm = df['Revs'].diff().abs().fillna(0)      # скачок оборотов между строками
    stable = d_rpm <= 30                           # без переходных процессов
    modes = {
        'running': running,
        'warm': warm,
        'stable': stable,
        # ХХ: прогрет, обороты в окне, машина стоит, дроссель закрыт, режим стабилен
        'idle': running & warm & df['Revs'].between(650, 950) &
                (df['Speed'] == 0) & (df['ThrottleAngle'] <= 6) & stable,
        # нагрузка: обороты и дроссель одновременно высоки (исключает манёвры на парковке)
        'load': running & warm & (df['Revs'] >= 1500) & (df['ThrottleAngle'] >= 8),
        # выбег: движемся, газ отпущен, обороты высокие — зона возможного fuel cut
        'decel': (df['Speed'] >= 20) & (df['ThrottleAngle'] <= 2) & (df['Revs'] > 1200),
    }
    return modes, inj_mean

# ---------------- Тест 1. Форсунки: баланс по цилиндрам ----------------
def test_injectors(df, modes, inj_mean):
    lines = []
    # глитчи канала (>15 мс) выбрасываем целиком
    glitch_free = (df[INJ_COLS] < 15).all(axis=1)
    for mode in ('idle', 'load'):
        m = modes[mode] & glitch_free
        n = int(m.sum())
        if n < 30:
            lines.append(f"  [~] форсунки ({mode}): мало точек ({n}), тест пропущен")
            continue
        means = df.loc[m, INJ_COLS].mean()
        dev = (means / means.mean() - 1) * 100
        worst_c = dev.abs().idxmax()
        worst_v = dev[worst_c]
        status = '[ok]' if abs(worst_v) <= 5 else '[!!]'
        devs = ', '.join(f"ц{c[4]} {v:+.1f}%" for c, v in dev.items())
        lines.append(
            f"  {status} форсунки ({mode}, {n} тч): отклонение средних — {devs} "
            f"(порог 5%; поэпизодный разброс НЕ смотреть — шум квантования ~7% на импульсе 1.3 мс)"
        )
    return lines

# ---------------- Тест 2. VVT: ошибка факт/задание ----------------
def test_vvt(df, modes):
    err = df['InCamDephaser'] - df['InCamDephaserInstr']
    base = modes['warm'] & modes['running'] & (df['Revs'] > 650)
    stable = base & modes['stable']
    lines = []
    n = int(stable.sum())
    if n < 30:
        return [f"  [~] VVT: мало стабильных точек ({n}), тест пропущен"]
    med = err[stable].median()
    p95 = err[stable].abs().quantile(0.95)
    status = '[ok]' if abs(med) <= 3 and p95 <= 8 else '[!!]'
    lines.append(
        f"  {status} VVT (стабильные режимы, {n} тч): медиана ошибки {med:+.1f}°, "
        f"p95 |ошибки| {p95:.1f}° (порог: медиана 3°, p95 8°)"
    )
    # переходные выбросы — отдельно, это не диагноз
    trans = base & (err.abs() > 10) & ~modes['stable']
    if trans.sum():
        worst_i = err[trans].abs().idxmax()
        lines.append(
            f"  [~] VVT переходные: {int(trans.sum())} тч с |ошибкой|>10° — "
            f"худшая {err[worst_i]:+.0f}° @ {df.loc[worst_i,'Time']} "
            f"(об {df.loc[worst_i,'Revs']:.0f}) — норма для переключения фаз"
        )
    return lines

# ---------------- Тест 3. Детонация: только при активном пороге ----------------
def test_knock(df, modes):
    thr = df['KnockSensorThr']
    armed = thr > 0                     # сенсор активирован ЭБУ; при Thr=0 любое шевеление — шум
    ex = (df['KnockSensor'] > thr) & armed
    lines = []
    n_load = int((ex & modes['load']).sum())
    n_other = int((ex & ~modes['load']).sum())
    n_armed = int(armed.sum())
    if n_armed < 30:
        return [f"  [~] детонация: порог активен лишь в {n_armed} тч, тест пропущен"]
    ratio = df['KnockSensor'][ex] / thr[ex] if ex.any() else pd.Series(dtype=float)
    status = '[ok]' if n_load <= 4 else '[!!]'
    lines.append(
        f"  {status} детонация: превышений при активном пороге {int(ex.sum())} "
        f"из {n_armed} вооружённых тч — в нагрузке {n_load}, вне (манёвры/выбег) {n_other} "
        f"(порог тревоги: 5 в нагрузке)"
    )
    if ex.any():
        worst_i = (df['KnockSensor'] / thr.replace(0, np.nan)).idxmax()
        tag = 'нагрузка' if modes['load'][worst_i] else 'манёвр/выбег'
        lines.append(
            f"  [~] детонация: пик {df.loc[worst_i,'KnockSensor']:.2f} при пороге {thr[worst_i]:.2f} "
            f"@ {df.loc[worst_i,'Time']} ({tag}, об {df.loc[worst_i,'Revs']:.0f}, "
            f"скор {df.loc[worst_i,'Speed']:.0f}) — {'проверить режим' if tag=='нагрузка' else 'шум, не диагноз'}"
        )
    return lines

# ---------------- Тест 4. Fuel cut: отсечка топлива на выбеге ----------------
def test_fuelcut(df, modes, inj_mean):
    cut = (inj_mean < 0.1) & modes['decel']
    lines = []
    n_decel = int(modes['decel'].sum())
    if n_decel < 20:
        return [f"  [~] fuel cut: выбегов в логе мало ({n_decel} тч) — нужен заезд: "
                f"3-4 торможения двигателем с 60 км/ч на 3-й без газа"]
    idx = df.index[cut]
    if len(idx) == 0:
        # мотор ни разу не отсёк топливо на доступных выбегах — повод, но не приговор:
        # ЭБУ может не резать на малых скоростях/выбегах
        lines.append(
            f"  [!!] fuel cut: на {n_decel} тч выбега отсечка НЕ зафиксирована ни разу "
            f"(инжекторы мин {inj_mean[modes['decel']].min():.2f} мс) — проверить на заезде с длинными выбегами"
        )
        return lines
    episodes = (np.diff(idx) > 3).sum() + 1
    total_s = len(idx) * 0.5  # грубо, при медианном шаге 0.5 с
    lines.append(
        f"  [ok] fuel cut: {episodes} эпизодов, суммарно ~{total_s:.0f} с "
        f"(об {df.loc[cut,'Revs'].min():.0f}-{df.loc[cut,'Revs'].max():.0f}) — отсечка работает"
    )
    return lines

# ---------------- Обёртка ----------------
def run_engine_tests(df):
    """Возвращает список строк отчёта по 4 тестам. df — DataFrame MED17-лога."""
    df = df.copy()
    for c in df.columns:
        if c not in ('Date', 'Time', 'Gear', 'BR', 'Errors'):
            df[c] = pd.to_numeric(df[c], errors='coerce')
    modes, inj_mean = build_modes(df)
    out = []
    out += test_injectors(df, modes, inj_mean)
    out += test_vvt(df, modes)
    out += test_knock(df, modes)
    out += test_fuelcut(df, modes, inj_mean)
    return out
