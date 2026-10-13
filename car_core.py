# -*- coding: utf-8 -*-
"""
car_core.py v4.2 — ядро: загрузка, режимы, поездки.
Запуск: python car_core.py [папка_с_логами]   (по умолчанию: папка скрипта/raw)
Логика границ записи (подтверждена владельцем):
  - выключение зажигания обесточивает ELM => запись рвётся РЕЗКО;
    последняя строка перед обрывом: Speed=0, Gear=P, обороты ~ХХ
  - потеря связи на ходу: пауза при движении => поездка НЕ рвётся (LINK_LOSS)
  - запинки ELM < 60 с => та же поездка
  - пауза > 10 мин => SHUTDOWN безусловно
  - охлаждение ОЖ > 10 C за паузу => SHUTDOWN даже без портрета
v4.2: режим IGN (зажигание вкл / двигатель заглушен): Battery<12.8 & нет впрыска;
      стретчи собираются через редкую запись логгера (разрыв до 120 с);
      длительность >= 10 с рвёт поездку меткой STOP_IGN (один разрыв на стретч);
      dt>10 с не раздувает километры; FULL_LOAD приоритетнее LOAD;
      поездки короче 30 с не печатаются; части -1/-2 пропускаются при слитом файле.
"""
import sys, os, glob
import numpy as np
import pandas as pd

COLS_NUM = ["Inj.1Time","Inj.2Time","Inj.3Time","Inj.4Time","Cyl.1Adv","Cyl.2Adv","Cyl.3Adv","Cyl.4Adv",
"Cyl.1AdvCorr","Cyl.2AdvCorr","Cyl.3AdvCorr","Cyl.4AdvCorr","UpO2Volt","DownO2Volt","UpO2Heat","DownO2Heat",
"UpMixCorr","DownMixCorr","AirManifold","Coolant","OilTemp","AtmosphPress","FuelPressInstr","FuelPress",
"FuelPressReg","AlternatorTemp","AlternatorCurrent","ECUtemp","Battery","FuelLevel","AirCPress","Speed",
"ExternalTemp","Revs","TurboInstr","TurboPress","IntakeAirPressInstr","IntakeAirPress","OilPressInstr",
"OilPress","AirFlowInstr","AirFlow","ThrottleAngleInstr","ThrottleAngle","InCamDephaserInstr","InCamDephaser",
"InCamDephaserValve","TorqIgnAdvInstr","TorqIgnAdv","TorqAirFlowInstr","TorqAirFlow","TorqLost","TurboWastegate",
"TurboBlowOff","AccelPedalPos","AlternatorCharge","OilPumpValve","KnockSensor","KnockSensorThr","Errors","BR"]

PAUSE_MERGE = 60      # запинки ELM короче — та же поездка
PAUSE_FORCE = 600     # пауза дольше 10 мин — глушение безусловно
COOL_DROP   = 10      # падение ОЖ за паузу, C — признак глушения
IGN_GAP = 120         # макс разрыв между строками, чтобы продолжить IGN-стретч
IGN_MIN = 10          # мин длительность IGN-стретча, чтобы рвать поездку


def load(path):
    df = pd.read_csv(path, sep=";", low_memory=False)
    ts = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str),
                        format="%Y.%m.%d %H:%M:%S.%f", errors="coerce")
    bad = ts.isna()
    if bad.any():
        ts.loc[bad] = pd.to_datetime(df.loc[bad,"Date"].astype(str)+" "+df.loc[bad,"Time"].astype(str),
                                     format="%Y.%m.%d %H:%M:%S", errors="coerce")
    df["ts"] = ts
    for c in COLS_NUM:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Gear"] = df["Gear"].astype(str).str.strip()
    return df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)


def classify(df):
    mode = np.full(len(df), "OTHER", dtype=object)
    spd  = df["Speed"].fillna(0).values
    revs = df["Revs"].fillna(0).values
    inj  = df[["Inj.1Time","Inj.2Time","Inj.3Time","Inj.4Time"]].fillna(0).values.max(axis=1)
    heat = df["UpO2Heat"].fillna(0).values
    o2   = df["UpO2Volt"].fillna(446).values
    cool = df["Coolant"].fillna(0).values
    thr  = df["ThrottleAngle"].fillna(0).values
    ped  = df["AccelPedalPos"].fillna(0).values
    # фантом: застрявший Revs при нулевом впрыске и холодном дефолте лямбд
    phantom = (spd==0)&(inj==0)&(heat==0)&(revs>=300)&(revs<=1200)&(np.abs(o2-446)<30)
    mode[phantom] = "OFF"
    off = revs==0
    mode[off & ~phantom] = "OFF"
    run = ~(off|phantom)
    crank = run & (revs>=200)&(revs<800)&(inj>10)&(spd==0)
    mode[crank] = "CRANK"
    warm = run & ~crank & (cool<60) & (spd==0)
    mode[warm] = "WARMUP"
    idle_cold = run & ~crank & ~warm & (cool>=60)&(cool<75)&(spd==0)&(thr<=8)&(revs>=650)&(revs<=1200)
    mode[idle_cold] = "IDLE_COLD"
    idle_warm = run & ~crank & ~warm & (cool>=75)&(spd==0)&(thr<=8)&(revs>=650)&(revs<=1200)
    mode[idle_warm] = "IDLE_WARM"
    mode[run & ~crank & (spd==0) & ~(warm|idle_cold|idle_warm)] = "OTHER"
    coast = run & (spd>0)&(thr<8)&(revs>1200)
    mode[coast] = "COAST"
    mode[run & (spd>0)&(thr<8)&(revs<=1200) & ~coast] = "DRIVE_LOW"
    mode[run & (thr>=8)&(thr<20) & (spd>0)] = "PART_LOAD"
    mode[run & (ped>=85)] = "FULL_LOAD"   # до LOAD: приоритет над LOAD/PART_LOAD
    mode[run & (thr>=20)] = "LOAD"

    # IGN: зажигание вкл, двигатель не работает.
    # Стретч тянется через редкую запись логгера (после глушения строки идут
    # раз в десятки секунд), но рвётся при работающем моторе или паузе > IGN_GAP.
    bat  = df["Battery"].values
    bat  = np.where(np.isnan(bat), 99.0, bat)   # NaN-батарею IGN-ом не считаем
    ts   = df["ts"].values
    ign_cand = (spd==0)&(~run)&(bat<12.8)
    ign = np.zeros(len(df), dtype=bool)
    i = 0; n = len(df)
    while i < n:
        if ign_cand[i]:
            j = i; last = i; k = i+1
            while k < n:
                if run[k]: break
                g = (ts[k]-ts[last])/np.timedelta64(1,"s")
                if g > IGN_GAP: break
                if ign_cand[k]: j = k
                last = k; k += 1
            if (ts[j]-ts[i])/np.timedelta64(1,"s") >= IGN_MIN:
                ign[i:j+1] = True
            i = j+1
        else:
            i += 1
    df["ign"] = ign

    df["mode"] = mode
    df["stable"] = pd.Series(revs).diff().abs().values <= 30
    return df


def ign_stretches(df):
    """Список (i0, i1) IGN-стретчей длительностью >= IGN_MIN."""
    out = []
    ign = df["ign"].values
    i = 0; n = len(df)
    while i < n:
        if ign[i]:
            j = i
            while j+1 < n and ign[j+1]: j += 1
            if (df["ts"].iloc[j]-df["ts"].iloc[i]).total_seconds() >= IGN_MIN:
                out.append((i, j))
            i = j+1
        else:
            i += 1
    return out


def segment(df):
    gaps = np.diff(df["ts"].values)/np.timedelta64(1,"s")
    cool = df["Coolant"].values
    spd  = df["Speed"].fillna(0).values
    gear = df["Gear"].values
    # один разрыв на IGN-стретч
    break_before = np.zeros(len(df), dtype=bool)
    for i0, i1 in ign_stretches(df):
        break_before[i0] = True
    tid  = np.zeros(len(df), dtype=int)
    ends = {0: "EOF"}
    t = 0
    for i in range(len(df)-1):
        tid[i] = t
        g = gaps[i]
        if g < PAUSE_MERGE and not break_before[i+1]:
            continue
        if break_before[i+1]:
            ends[t] = "STOP_IGN"; t += 1; ends[t] = "EOF"; continue
        portret  = (spd[i]==0) and (gear[i] in ("P","N"))
        cd = (not np.isnan(cool[i])) and (not np.isnan(cool[i+1])) and (cool[i]-cool[i+1] > COOL_DROP)
        if g > PAUSE_FORCE or portret or cd:
            ends[t] = "SHUTDOWN"; t += 1; ends[t] = "EOF"
        else:
            ends[t] = "LINK_LOSS"
    tid[-1] = t
    df["trip"] = tid
    return df, ends


def report(df, ends, path):
    t0, t1 = df["ts"].iloc[0], df["ts"].iloc[-1]
    span = (t1-t0).total_seconds()/60
    dtn = np.diff(df["ts"].values)/np.timedelta64(1,"s")
    rec = dtn[dtn<PAUSE_MERGE].sum()/60
    print(f"\n=== {os.path.basename(path)}: {t0} — {t1} ===")
    print(f"Строк {len(df)}; записи {rec:.1f} мин, паузы {span-rec:.1f} мин; баланс {span:.1f} мин")
    n_loss = sum(1 for v in ends.values() if v=="LINK_LOSS")
    if n_loss: print(f"разрывов связи: {n_loss}")
    ign_tot = sum((df["ts"].iloc[j]-df["ts"].iloc[i]).total_seconds()/60.0 for i,j in ign_stretches(df))
    if ign_tot: print(f"зажигание без двигателя: {ign_tot:.1f} мин")
    n_art = int((df.groupby("trip").size()<5).sum())
    if n_art: print(f"мелких фрагментов (<5 строк): {n_art}")
    for tid, grp in df.groupby("trip"):
        if len(grp) < 5: continue
        t_a, t_b = grp["ts"].iloc[0], grp["ts"].iloc[-1]
        if (t_b-t_a).total_seconds() < 30: continue   # поездки короче 30 с не печатаем
        dur = (t_b-t_a).total_seconds()/60
        spd = grp["Speed"].fillna(0).values
        dts = np.append(np.diff(grp["ts"].values)/np.timedelta64(1,"s"), 0.0)
        dts[dts>10] = 0.0   # разрыв записи не «едет» со скоростью последней строки
        km = (spd*dts/3600).sum()
        vmax = grp["Speed"].fillna(0).max()
        cl = grp["Coolant"].dropna()
        c0, c1 = (cl.iloc[0], cl.iloc[-1]) if len(cl) else (np.nan, np.nan)
        stops = int(((spd[1:]==0)&(spd[:-1]>0)).sum())
        prof = grp["mode"].value_counts()*100/len(grp)
        profs = ", ".join(f"{k} {v:.0f}%" for k,v in prof.sort_values(ascending=False).items() if v>=4)
        print(f"Поездка: {t_a.strftime('%H:%M:%S')}-{t_b.strftime('%H:%M:%S')}  {dur:.1f} мин, {km:.1f} км, "
              f"макс {vmax:.0f} км/ч, ОЖ {c0:.0f}-{c1:.0f} C, остановок {stops} [{ends.get(tid,'EOF')}]")
        if profs: print(f"    профиль: {profs}")


def process_file(path):
    df = load(path)
    df = classify(df)
    df, ends = segment(df)
    report(df, ends, path)
    return df


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
    files = sorted(glob.glob(os.path.join(folder, "MED17*.csv")))
    if not files:
        print(f"MED17-файлы в {folder} не найдены"); return
    by_date = {}
    for p in files:
        base = os.path.basename(p)
        date = base.split("_")[-1].split(".")[0]           # 20261006
        suffixed = "-" in base.replace("MED17_4_2_", "")   # части -1, -2...
        by_date.setdefault(date, []).append((suffixed, p))
    chosen = []
    for date, lst in sorted(by_date.items()):
        full = [p for s, p in lst if not s]
        chosen += full if full else [p for _, p in lst]
    print(f"Найдено файлов: {len(files)}; к обработке: {len(chosen)}")
    for p in chosen:
        process_file(p)

if __name__ == "__main__":
    main()
