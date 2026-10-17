"""GéniePont & Sous-sol — application Streamlit tout-en-un (un seul fichier).

Collecte de données, analyse et pré-dimensionnement (pont, sous-sol).
Lancer :  streamlit run app.py
Dépendances :  pip install streamlit plotly pandas numpy openpyxl
Pré-dimensionnement uniquement : à faire valider par un ingénieur.
"""
from __future__ import annotations

import io
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ============================================================================
# 1) CALCULS DE GÉNIE CIVIL
# ============================================================================
GAMMA_C = 1.5
GAMMA_S = 1.15
GAMMA_W = 9.81  # kN/m3
GAMMA_BETON = 25.0  # kN/m3


# --------------------------------------------------------------------------
# PONT : poutre en béton armé simplement appuyée (section rectangulaire)
# --------------------------------------------------------------------------
@dataclass
class ResultatPont:
    L: float
    b: float
    h: float
    d: float
    g_total: float
    q: float
    w_elu: float
    w_els: float
    M_ed: float
    V_ed: float
    mu: float
    section_ok: bool
    z: float
    As_req: float
    As_min: float
    As_retenue: float
    n_barres: int
    diam: int
    As_fournie: float
    V_rdc: float
    V_rdmax: float
    asw_s: float          # cm2/m d'armatures d'effort tranchant (cadres)
    cadres_requis: bool
    cisaillement_ok: bool
    fleche: float
    fleche_lim: float
    fleche_ok: bool
    taux_flexion: float
    messages: list[str] = field(default_factory=list)


def module_young_beton(fck: float) -> float:
    """Ecm en MPa (EC2 tab. 3.1)."""
    return 22000.0 * ((fck + 8.0) / 10.0) ** 0.3


def dimensionner_pont(
    L: float,
    b: float,
    h: float,
    fck: float = 30.0,
    fyk: float = 500.0,
    enrobage: float = 0.04,
    diam: int = 25,
    g_sup: float = 15.0,
    q: float = 30.0,
    phi_fluage: float = 2.0,
    limite_fleche: int = 250,
) -> ResultatPont:
    """Dimensionne en flexion/cisaillement/flèche une poutre de pont isostatique.

    L, b, h, enrobage en m ; g_sup (charges permanentes additionnelles) et q
    (exploitation) en kN/m.
    """
    if min(L, b, h) <= 0:
        raise ValueError("L, b et h doivent être strictement positifs.")
    msgs: list[str] = []
    d = h - enrobage - diam / 2000.0
    g_pp = GAMMA_BETON * b * h
    g_total = g_pp + g_sup
    w_elu = 1.35 * g_total + 1.5 * q
    w_els = g_total + q

    M_ed = w_elu * L**2 / 8.0  # kN.m
    V_ed = w_elu * L / 2.0  # kN

    fcd = fck / GAMMA_C
    fyd = fyk / GAMMA_S
    mu = (M_ed * 1e-3) / (b * d**2 * fcd)  # MN.m / (m3 * MPa)
    mu_lim = 0.372
    section_ok = mu <= mu_lim
    if section_ok:
        alpha = 1.25 * (1 - math.sqrt(1 - 2 * mu))
        z = d * (1 - 0.4 * alpha)
        As_req = (M_ed * 1e-3) / (z * fyd) * 1e4  # cm2
    else:
        z = 0.8 * d
        As_req = float("nan")
        msgs.append(
            "Section insuffisante en flexion simple (µ > 0,372) : augmenter h, b ou fck."
        )

    fctm = 0.30 * fck ** (2.0 / 3.0)
    As_min = max(0.26 * fctm / fyk * b * d, 0.0013 * b * d) * 1e4  # cm2
    As_ret = max(As_req, As_min) if section_ok else float("nan")

    area_bar = math.pi * (diam / 10.0) ** 2 / 4.0  # cm2
    n_bar = int(math.ceil(As_ret / area_bar)) if section_ok else 0
    As_four = n_bar * area_bar

    # Cisaillement sans armatures d'effort tranchant (VRd,c, EC2 6.2.2)
    d_mm = d * 1000.0
    k = min(1 + math.sqrt(200.0 / d_mm), 2.0)
    rho = min((As_four if section_ok else 0.0) / ((b * 100.0) * (d * 100.0)), 0.02)
    crd = 0.18 / GAMMA_C
    v_rdc1 = crd * k * (100 * rho * fck) ** (1 / 3)
    v_min = 0.035 * k**1.5 * math.sqrt(fck)
    V_rdc = max(v_rdc1, v_min) * (b * 1000.0) * d_mm / 1000.0  # kN
    # Bielle de béton (VRd,max) et cadres (méthode des bielles, cot(theta)=2,5)
    cot = 2.5
    nu1 = 0.6 * (1 - fck / 250.0)
    z_cis = 0.9 * d
    V_rdmax = nu1 * fcd * (b * 1000.0) * (z_cis * 1000.0) / (cot + 1 / cot) / 1000.0  # kN
    cadres_requis = V_ed > V_rdc
    fywd = fyk / GAMMA_S
    asw_calc = (V_ed * 1e-3) / (z_cis * fywd * cot) * 1e4  # cm2/m
    asw_min = 0.08 * math.sqrt(fck) / fyk * b * 1e4  # cm2/m
    asw_s = max(asw_calc if cadres_requis else 0.0, asw_min)
    cis_ok = V_ed <= V_rdmax
    if not cis_ok:
        msgs.append("V_Ed > V_Rd,max : la bielle de béton est insuffisante, augmenter b, h ou fck.")
    elif cadres_requis:
        msgs.append(f"Cadres d'effort tranchant nécessaires : au moins {asw_s:.1f} cm²/m (à l'appui).")

    # Flèche ELS (poutre isostatique, module effectif avec fluage)
    Ecm = module_young_beton(fck)
    E_eff = Ecm / (1 + phi_fluage)
    I = b * h**3 / 12.0
    # fluage appliqué aux charges permanentes, module instantané pour l'exploitation
    fleche = 5 * L**4 / (384 * I) * (g_total / (E_eff * 1e3) + q / (Ecm * 1e3)) * 1000.0  # mm
    f_lim = L * 1000.0 / limite_fleche
    f_ok = fleche <= f_lim
    if not f_ok:
        msgs.append("Flèche supérieure à la limite : augmenter la hauteur h de la poutre.")

    taux = mu / mu_lim
    return ResultatPont(
        L=L, b=b, h=h, d=d, g_total=g_total, q=q, w_elu=w_elu, w_els=w_els,
        M_ed=M_ed, V_ed=V_ed, mu=mu, section_ok=section_ok, z=z, As_req=As_req,
        As_min=As_min, As_retenue=As_ret, n_barres=n_bar, diam=diam,
        As_fournie=As_four, V_rdc=V_rdc, V_rdmax=V_rdmax, asw_s=asw_s,
        cadres_requis=cadres_requis, cisaillement_ok=cis_ok, fleche=fleche,
        fleche_lim=f_lim, fleche_ok=f_ok, taux_flexion=taux, messages=msgs,
    )


def diagrammes_poutre(L: float, w: float, n: int = 101):
    """x, V(x), M(x) pour une charge uniforme w sur poutre isostatique."""
    x = np.linspace(0, L, n)
    V = w * (L / 2 - x)
    M = w * x * (L - x) / 2
    return x, V, M


def optimiser_hauteur(L, b, **kw) -> float | None:
    """Plus petite hauteur h (pas 5 cm) qui vérifie flexion, cisaillement et flèche."""
    h = 0.30
    while h <= 4.0:
        r = dimensionner_pont(L, b, round(h, 2), **kw)
        if r.section_ok and r.cisaillement_ok and r.fleche_ok:
            return round(h, 2)
        h += 0.05
    return None


# --------------------------------------------------------------------------
# SOUS-SOL : voile enterré, poussée des terres, nappe, semelle
# --------------------------------------------------------------------------
def coeff_poussee(phi_deg: float, repos: bool = False) -> float:
    phi = math.radians(phi_deg)
    if repos:
        return 1 - math.sin(phi)
    return math.tan(math.radians(45) - phi / 2) ** 2


def profil_poussee(H, gamma, phi, surcharge=10.0, prof_nappe=None,
                   gamma_sat=None, repos=True, n=201):
    """Pression horizontale totale (kPa) sur le voile en fonction de la profondeur z."""
    gamma_sat = gamma_sat if gamma_sat is not None else gamma + 2.0
    K = coeff_poussee(phi, repos)
    z = np.linspace(0, H, n)
    sig_v = np.zeros_like(z)
    u = np.zeros_like(z)
    for i, zi in enumerate(z):
        if prof_nappe is None or zi <= prof_nappe:
            sig_v[i] = gamma * zi + surcharge
        else:
            sig_v[i] = (gamma * prof_nappe + surcharge
                        + (gamma_sat - GAMMA_W) * (zi - prof_nappe))
            u[i] = GAMMA_W * (zi - prof_nappe)
    p = K * sig_v + u
    return z, p, K


@dataclass
class ResultatVoile:
    K: float
    force: float       # kN par m de voile
    bras: float        # m, mesuré depuis la base
    M_base: float      # kN.m/m (moment d'encastrement, ELS)
    M_ed: float        # ELU
    As_req: float      # cm2/m
    As_min: float
    epaisseur_ok: bool
    d: float
    z: np.ndarray
    p: np.ndarray


def dimensionner_voile(H, e, gamma=18.0, phi=30.0, surcharge=10.0,
                       prof_nappe=None, repos=True, fck=30.0, fyk=500.0,
                       enrobage=0.05, diam=16) -> ResultatVoile:
    """Voile console encastré à la base, bande de 1 m."""
    z, p, K = profil_poussee(H, gamma, phi, surcharge, prof_nappe, repos=repos)
    F = float(np.trapezoid(p, z))
    M = float(np.trapezoid(p * (H - z), z))
    bras = M / F if F > 0 else 0.0
    M_ed = 1.35 * M
    d = e - enrobage - diam / 2000.0
    fcd, fyd = fck / GAMMA_C, fyk / GAMMA_S
    mu = (M_ed * 1e-3) / (1.0 * d**2 * fcd)
    if mu <= 0.372:
        alpha = 1.25 * (1 - math.sqrt(1 - 2 * mu))
        zb = d * (1 - 0.4 * alpha)
        As = (M_ed * 1e-3) / (zb * fyd) * 1e4
        ok = True
    else:
        As, ok = float("nan"), False
    fctm = 0.30 * fck ** (2.0 / 3.0)
    As_min = max(0.26 * fctm / fyk * 1.0 * d, 0.0013 * 1.0 * d) * 1e4
    return ResultatVoile(K, F, bras, M, M_ed, As, As_min, ok, d, z, p)


@dataclass
class ResultatSemelle:
    Nq: float
    Nc: float
    Ngamma: float
    q_ultime: float
    q_adm: float
    q_appliquee: float
    taux: float
    portance_ok: bool
    tassement_mm: float
    tassement_ok: bool


def capacite_portante(B, L, N_ser, D, gamma, phi, c=0.0, E_sol=20000.0,
                      nu=0.3, FS=3.0, tassement_max_mm=25.0) -> ResultatSemelle:
    """Terzaghi/Vesić pour une semelle rectangulaire B x L (m), charge N_ser (kN),
    encastrement D (m), cohésion c et module E_sol en kPa."""
    ph = math.radians(phi)
    Nq = math.exp(math.pi * math.tan(ph)) * math.tan(math.radians(45) + ph / 2) ** 2
    Nc = (Nq - 1) / math.tan(ph) if phi > 0 else 5.14
    Ng = 2 * (Nq + 1) * math.tan(ph)
    sq = 1 + (B / L) * math.sin(ph)
    sg = max(1 - 0.3 * B / L, 0.6)
    sc = (sq * Nq - 1) / (Nq - 1) if phi > 0 else 1 + 0.2 * B / L
    q0 = gamma * D
    qu = c * Nc * sc + q0 * Nq * sq + 0.5 * gamma * B * Ng * sg
    q_adm = qu / FS
    q_app = N_ser / (B * L)
    s = q_app * B * (1 - nu**2) / E_sol * 0.82 * 1000.0
    return ResultatSemelle(Nq, Nc, Ng, qu, q_adm, q_app, q_app / q_adm,
                           q_app <= q_adm, s, s <= tassement_max_mm)


@dataclass
class ResultatFlottaison:
    poids: float
    poussee: float
    FS: float
    ok: bool
    lest_requis: float


def verif_soulevement(poids_total, aire, hauteur_eau, FS_min=1.1) -> ResultatFlottaison:
    """Stabilité au soulèvement (poussée d'Archimède) d'un sous-sol sous la nappe."""
    U = GAMMA_W * max(hauteur_eau, 0.0) * aire
    FS = poids_total / U if U > 0 else float("inf")
    lest = max(FS_min * U - poids_total, 0.0)
    return ResultatFlottaison(poids_total, U, FS, FS >= FS_min, lest)

# ============================================================================
# 2) DONNÉES : base SQLite, démo, analyse
# ============================================================================
DB_PATH = Path(__file__).parent / "data" / "projet.db"

COLONNES = ["horodatage", "ouvrage", "capteur", "grandeur", "valeur", "unite", "operateur", "remarque"]

# Seuil d'alerte par grandeur (valeur absolue maximale admissible)
SEUILS = {
    "Flèche": ("mm", 30.0),
    "Déformation": ("µε", 600.0),
    "Fissure": ("mm", 0.30),
    "Tassement": ("mm", 25.0),
    "Pression interstitielle": ("kPa", 60.0),
    "Niveau de nappe": ("m", 4.0),
    "Température": ("°C", 45.0),
}

OUVRAGES = ["Pont P1", "Sous-sol S1"]


def connexion() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS mesures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            horodatage TEXT NOT NULL,
            ouvrage TEXT NOT NULL,
            capteur TEXT NOT NULL,
            grandeur TEXT NOT NULL,
            valeur REAL NOT NULL,
            unite TEXT,
            operateur TEXT,
            remarque TEXT
        )"""
    )
    return con


def lire_mesures() -> pd.DataFrame:
    con = connexion()
    try:
        df = pd.read_sql_query("SELECT * FROM mesures ORDER BY horodatage", con)
    finally:
        con.close()
    if not df.empty:
        df["horodatage"] = pd.to_datetime(df["horodatage"])
    return df


def ajouter_mesures(df: pd.DataFrame) -> int:
    """Insère un DataFrame (colonnes de COLONNES). Retourne le nombre de lignes."""
    manquantes = {"horodatage", "ouvrage", "capteur", "grandeur", "valeur"} - set(df.columns)
    if manquantes:
        raise ValueError(f"Colonnes manquantes : {', '.join(sorted(manquantes))}")
    d = df.copy()
    for c in COLONNES:
        if c not in d.columns:
            d[c] = ""
    d["horodatage"] = pd.to_datetime(d["horodatage"], errors="coerce")
    d["valeur"] = pd.to_numeric(d["valeur"], errors="coerce")
    d = d.dropna(subset=["horodatage", "valeur"])
    d["horodatage"] = d["horodatage"].dt.strftime("%Y-%m-%d %H:%M:%S")
    con = connexion()
    try:
        con.executemany(
            f"INSERT INTO mesures ({','.join(COLONNES)}) VALUES ({','.join('?' * len(COLONNES))})",
            d[COLONNES].astype(object).where(d[COLONNES].notna(), "").values.tolist(),
        )
        con.commit()
    finally:
        con.close()
    return len(d)


def vider_base() -> None:
    con = connexion()
    try:
        con.execute("DELETE FROM mesures")
        con.commit()
    finally:
        con.close()


def generer_demo(jours: int = 90, pas_heures: int = 6, graine: int = 42) -> pd.DataFrame:
    """Données réalistes : fluage lent, cycle thermique, pic de pluie, quelques anomalies."""
    rng = np.random.default_rng(graine)
    fin = datetime.now().replace(minute=0, second=0, microsecond=0)
    t = pd.date_range(end=fin, periods=jours * 24 // pas_heures, freq=f"{pas_heures}h")
    n = len(t)
    jour = np.arange(n) * pas_heures / 24.0
    temp = 18 + 8 * np.sin(2 * np.pi * (jour % 1.0) - 1.5) + 4 * np.sin(2 * np.pi * jour / 60)
    pluie = np.exp(-((jour - jours * 0.7) ** 2) / 40)  # épisode pluvieux

    series = {
        ("Pont P1", "FL-01", "Flèche", "mm"): 6 + 0.12 * jour**0.9 + 0.25 * (temp - 18) + rng.normal(0, 0.3, n),
        ("Pont P1", "JA-02", "Déformation", "µε"): 180 + 2.2 * jour + 9 * (temp - 18) + rng.normal(0, 8, n),
        ("Pont P1", "FI-03", "Fissure", "mm"): 0.08 + 0.0018 * jour + rng.normal(0, 0.006, n),
        ("Pont P1", "TH-04", "Température", "°C"): temp + rng.normal(0, 0.4, n),
        ("Sous-sol S1", "TA-05", "Tassement", "mm"): 4 * np.log1p(jour) + 3 * pluie + rng.normal(0, 0.25, n),
        ("Sous-sol S1", "PZ-06", "Pression interstitielle", "kPa"): 25 + 22 * pluie + rng.normal(0, 1.2, n),
        ("Sous-sol S1", "NP-07", "Niveau de nappe", "m"): 2.0 + 1.6 * pluie + rng.normal(0, 0.05, n),
    }
    lignes = []
    for (ouv, cap, gr, un), v in series.items():
        v = np.array(v, dtype=float)
        idx = rng.choice(n, size=max(2, n // 150), replace=False)  # anomalies
        v[idx] += rng.choice([-1, 1], len(idx)) * np.abs(v).mean() * 0.25
        lignes.append(pd.DataFrame({
            "horodatage": t, "ouvrage": ouv, "capteur": cap, "grandeur": gr,
            "valeur": np.round(v, 3), "unite": un, "operateur": "Automatique", "remarque": "",
        }))
    return pd.concat(lignes, ignore_index=True)


# ---------------------------------------------------------------------- analyse
def statistiques(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["ouvrage", "capteur", "grandeur", "unite"])["valeur"]
    s = g.agg(["count", "mean", "std", "min", "max"]).reset_index()
    s["dernière"] = g.last().values
    return s.round(3)


def tendance(df: pd.DataFrame):
    """Régression linéaire valeur = a*jours + b. Retourne (pente/jour, ordonnée, r2)."""
    if len(df) < 3:
        return 0.0, float(df["valeur"].mean() if len(df) else 0.0), 0.0
    x = (df["horodatage"] - df["horodatage"].min()).dt.total_seconds() / 86400.0
    a, b = np.polyfit(x, df["valeur"], 1)
    pred = a * x + b
    ss_res = float(((df["valeur"] - pred) ** 2).sum())
    ss_tot = float(((df["valeur"] - df["valeur"].mean()) ** 2).sum())
    return float(a), float(b), 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


def jours_avant_seuil(df: pd.DataFrame, seuil: float):
    """Nombre de jours restants avant d'atteindre le seuil selon la tendance (None si pas de dérive)."""
    a, b, _ = tendance(df)
    if a <= 0:
        return None
    x_now = (df["horodatage"].max() - df["horodatage"].min()).total_seconds() / 86400.0
    restant = (seuil - b) / a - x_now
    return max(restant, 0.0)


def detecter_anomalies(df: pd.DataFrame, fenetre: int = 24, z_max: float = 3.0) -> pd.DataFrame:
    """Anomalie = écart à la moyenne glissante supérieur à z_max écarts-types glissants."""
    d = df.sort_values("horodatage").copy()
    moy = d["valeur"].rolling(fenetre, min_periods=max(3, fenetre // 4), center=True).mean()
    sd = d["valeur"].rolling(fenetre, min_periods=max(3, fenetre // 4), center=True).std()
    d["z"] = (d["valeur"] - moy) / sd.replace(0, np.nan)
    d["anomalie"] = d["z"].abs() > z_max
    return d


def etat_alertes(df: pd.DataFrame) -> pd.DataFrame:
    """Dernière valeur de chaque capteur comparée au seuil → statut."""
    rows = []
    for (ouv, cap, gr, un), g in df.groupby(["ouvrage", "capteur", "grandeur", "unite"]):
        g = g.sort_values("horodatage")
        last = float(g["valeur"].iloc[-1])
        seuil = SEUILS.get(gr, (un, None))[1]
        if seuil is None:
            ratio, statut = np.nan, "Sans seuil"
        else:
            ratio = abs(last) / seuil
            statut = "Critique" if ratio >= 1 else "Vigilance" if ratio >= 0.8 else "Normal"
        rows.append({"ouvrage": ouv, "capteur": cap, "grandeur": gr, "unité": un,
                     "dernière valeur": round(last, 3), "seuil": seuil,
                     "taux d'atteinte": round(ratio, 3) if ratio == ratio else None,
                     "statut": statut})
    return pd.DataFrame(rows)


def vers_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for nom, d in sheets.items():
            d.to_excel(w, sheet_name=nom[:31], index=False)
    return buf.getvalue()

# ============================================================================
# 3) INTERFACE STREAMLIT
# ============================================================================
st.set_page_config(page_title="GéniePont & Sous-sol", page_icon="🌉", layout="wide")

# ----------------------------------------------------------------------------
# Thème fluide et dynamique : fond dégradé animé, cartes en verre, néons
# ----------------------------------------------------------------------------
CSS = """
<style>
@keyframes flow {0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes glow {0%,100%{box-shadow:0 0 12px rgba(0,212,255,.25)}50%{box-shadow:0 0 28px rgba(160,90,255,.45)}}
@keyframes rise {from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.stApp{background:linear-gradient(120deg,#0A1128,#14123a,#0b2a4a,#1a0f3c,#0A1128);
 background-size:400% 400%;animation:flow 22s ease infinite;}
[data-testid="stSidebar"]{background:linear-gradient(180deg,rgba(17,28,61,.95),rgba(26,15,60,.95));
 border-right:1px solid rgba(0,212,255,.25);}
h1,h2,h3{background:linear-gradient(90deg,#00D4FF,#7B61FF,#FF4ECD,#00D4FF);background-size:300% 100%;
 -webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:flow 8s linear infinite;}
.carte{background:rgba(255,255,255,.06);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.12);
 border-radius:16px;padding:16px 18px;margin-bottom:10px;animation:rise .6s ease both,glow 6s ease infinite;}
.carte .t{font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;opacity:.7}
.carte .v{font-size:1.9rem;font-weight:700;margin-top:2px}
.ok{color:#2EF2A0}.warn{color:#FFC857}.ko{color:#FF5C7A}
.bandeau{border-radius:14px;padding:14px 18px;margin:8px 0;font-weight:600;animation:rise .5s ease both}
.b-ok{background:linear-gradient(90deg,rgba(46,242,160,.22),rgba(0,212,255,.12));border:1px solid #2EF2A0}
.b-ko{background:linear-gradient(90deg,rgba(255,92,122,.25),rgba(255,78,205,.12));border:1px solid #FF5C7A}
.stButton>button,.stDownloadButton>button{background:linear-gradient(90deg,#00D4FF,#7B61FF,#FF4ECD);
 background-size:200% 100%;color:white;border:0;border-radius:12px;font-weight:700;transition:all .4s}
.stButton>button:hover,.stDownloadButton>button:hover{background-position:100% 0;transform:translateY(-2px) scale(1.02);
 box-shadow:0 8px 22px rgba(123,97,255,.5)}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

PALETTE = ["#00D4FF", "#7B61FF", "#FF4ECD", "#2EF2A0", "#FFC857", "#FF8A5C", "#5CB8FF"]


def style_fig(fig: go.Figure, titre: str = "", hauteur: int = 380) -> go.Figure:
    fig.update_layout(
        title=titre, height=hauteur, template="plotly_dark", colorway=PALETTE,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(255,255,255,0.03)",
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.2),
        transition=dict(duration=500, easing="cubic-in-out"),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.08)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.08)")
    return fig


def carte(titre: str, valeur: str, etat: str = "") -> None:
    st.markdown(f'<div class="carte"><div class="t">{titre}</div>'
                f'<div class="v {etat}">{valeur}</div></div>', unsafe_allow_html=True)


def bandeau(ok: bool, texte: str) -> None:
    st.markdown(f'<div class="bandeau {"b-ok" if ok else "b-ko"}">{"✅" if ok else "⚠️"} {texte}</div>',
                unsafe_allow_html=True)


@st.cache_data(show_spinner=False, ttl=5)
def charger() -> pd.DataFrame:
    return lire_mesures()


def rafraichir() -> None:
    charger.clear()


# ----------------------------------------------------------------------------
# Navigation
# ----------------------------------------------------------------------------
st.sidebar.title("🌉 GéniePont")
st.sidebar.caption("Pont · Sous-sol · Dimensionnement")
page = st.sidebar.radio(
    "Navigation",
    ["📊 Tableau de bord", "📥 Collecte de données", "📈 Analyse", "🌉 Dimensionnement pont",
     "🕳️ Dimensionnement sous-sol", "📤 Export"],
    label_visibility="collapsed",
)
st.sidebar.divider()
st.sidebar.info("Pré-dimensionnement uniquement : à faire valider par un ingénieur structure / géotechnicien.")

df = charger()

# ============================================================================
# TABLEAU DE BORD
# ============================================================================
if page.startswith("📊"):
    st.title("Tableau de bord du chantier")
    if df.empty:
        st.warning("Aucune donnée pour l'instant. Allez dans « Collecte de données » pour importer un fichier, "
                   "saisir des mesures ou générer des données de démonstration.")
    else:
        alertes = etat_alertes(df)
        c1, c2, c3, c4 = st.columns(4)
        with c1: carte("Mesures", f"{len(df):,}".replace(",", " "))
        with c2: carte("Capteurs actifs", str(df["capteur"].nunique()))
        nb_crit = int((alertes["statut"] == "Critique").sum())
        nb_vig = int((alertes["statut"] == "Vigilance").sum())
        with c3: carte("En vigilance", str(nb_vig), "warn" if nb_vig else "ok")
        with c4: carte("Critiques", str(nb_crit), "ko" if nb_crit else "ok")

        g1, g2 = st.columns([3, 2])
        with g1:
            fig = go.Figure()
            for i, ((ouv, cap, gr), g) in enumerate(df.groupby(["ouvrage", "capteur", "grandeur"])):
                s = g.sort_values("horodatage")
                base = s["valeur"].iloc[0] or 1.0
                fig.add_trace(go.Scatter(x=s["horodatage"], y=s["valeur"] / abs(base) * 100,
                                         name=f"{cap} · {gr}", mode="lines", line=dict(width=2)))
            st.plotly_chart(style_fig(fig, "Évolution relative des capteurs (base 100 = 1re mesure)", 420))
        with g2:
            a = alertes.dropna(subset=["taux d'atteinte"]).sort_values("taux d'atteinte")
            couleurs = ["#FF5C7A" if r >= 1 else "#FFC857" if r >= .8 else "#2EF2A0" for r in a["taux d'atteinte"]]
            fig = go.Figure(go.Bar(x=a["taux d'atteinte"] * 100, y=a["capteur"] + " · " + a["grandeur"],
                                   orientation="h", marker_color=couleurs))
            fig.add_vline(x=100, line_dash="dash", line_color="#FF5C7A")
            st.plotly_chart(style_fig(fig, "Taux d'atteinte du seuil (%)", 420))
        st.subheader("État des capteurs")
        st.dataframe(alertes)

# ============================================================================
# COLLECTE
# ============================================================================
elif page.startswith("📥"):
    st.title("Collecte de données")
    t1, t2, t3, t4 = st.tabs(["✍️ Saisie manuelle", "📁 Import CSV / Excel", "🎲 Données de démo", "🗑️ Base"])

    with t1:
        with st.form("saisie", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            ouvrage = c1.selectbox("Ouvrage", OUVRAGES)
            grandeur = c2.selectbox("Grandeur", list(SEUILS))
            capteur = c3.text_input("Capteur", "C-01")
            c4, c5, c6 = st.columns(3)
            valeur = c4.number_input("Valeur", value=0.0, format="%.4f")
            date = c5.date_input("Date")
            heure = c6.time_input("Heure")
            operateur = st.text_input("Opérateur")
            remarque = st.text_area("Remarque", height=70)
            if st.form_submit_button("Enregistrer la mesure"):
                n = ajouter_mesures(pd.DataFrame([{
                    "horodatage": pd.Timestamp.combine(date, heure), "ouvrage": ouvrage, "capteur": capteur,
                    "grandeur": grandeur, "valeur": valeur, "unite": SEUILS[grandeur][0],
                    "operateur": operateur, "remarque": remarque}]))
                rafraichir()
                st.success(f"{n} mesure enregistrée.")

    with t2:
        st.caption("Colonnes requises : horodatage, ouvrage, capteur, grandeur, valeur "
                   "(optionnelles : unite, operateur, remarque).")
        modele = pd.DataFrame([{"horodatage": "2026-10-01 08:00:00", "ouvrage": "Pont P1", "capteur": "FL-01",
                                "grandeur": "Flèche", "valeur": 7.2, "unite": "mm",
                                "operateur": "J. Dupont", "remarque": ""}])
        st.download_button("Télécharger un modèle CSV", modele.to_csv(index=False).encode("utf-8"),
                           "modele_mesures.csv", "text/csv")
        f = st.file_uploader("Fichier de mesures", type=["csv", "xlsx"])
        if f is not None:
            try:
                brut = pd.read_csv(f) if f.name.lower().endswith(".csv") else pd.read_excel(f)
                st.dataframe(brut.head(20))
                if st.button("Importer dans la base"):
                    n = ajouter_mesures(brut)
                    rafraichir()
                    st.success(f"{n} lignes importées.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Import impossible : {e}")

    with t3:
        jours = st.slider("Durée simulée (jours)", 10, 365, 90)
        if st.button("Générer des mesures de démonstration"):
            n = ajouter_mesures(generer_demo(jours))
            rafraichir()
            st.success(f"{n} mesures ajoutées (pont P1 et sous-sol S1).")

    with t4:
        st.write(f"**{len(df)}** mesures en base.")
        if not df.empty:
            st.dataframe(df.tail(200))
        if st.checkbox("Je confirme vouloir tout supprimer") and st.button("Vider la base"):
            vider_base()
            rafraichir()
            st.rerun()

# ============================================================================
# ANALYSE
# ============================================================================
elif page.startswith("📈"):
    st.title("Analyse des mesures")
    if df.empty:
        st.warning("Aucune donnée : utilisez d'abord la page « Collecte de données ».")
    else:
        f1, f2, f3 = st.columns(3)
        ouv = f1.multiselect("Ouvrage", sorted(df["ouvrage"].unique()), default=sorted(df["ouvrage"].unique()))
        sub = df[df["ouvrage"].isin(ouv)]
        grs = f2.multiselect("Grandeur", sorted(sub["grandeur"].unique()), default=sorted(sub["grandeur"].unique())[:1])
        sub = sub[sub["grandeur"].isin(grs)]
        dmin, dmax = df["horodatage"].min().date(), df["horodatage"].max().date()
        plage = f3.date_input("Période", (dmin, dmax), min_value=dmin, max_value=dmax)
        if isinstance(plage, tuple) and len(plage) == 2:
            sub = sub[(sub["horodatage"].dt.date >= plage[0]) & (sub["horodatage"].dt.date <= plage[1])]
        if sub.empty:
            st.info("Aucune mesure pour ce filtre.")
        else:
            tab1, tab2, tab3, tab4 = st.tabs(["Séries & tendance", "Anomalies", "Corrélations", "Statistiques"])
            with tab1:
                lissage = st.slider("Lissage (nombre de points)", 1, 60, 8)
                for gr in grs:
                    g = sub[sub["grandeur"] == gr]
                    fig = go.Figure()
                    for cap, s in g.groupby("capteur"):
                        s = s.sort_values("horodatage")
                        fig.add_trace(go.Scatter(x=s["horodatage"], y=s["valeur"], mode="markers", opacity=.35,
                                                 name=f"{cap} brut", marker=dict(size=4)))
                        fig.add_trace(go.Scatter(x=s["horodatage"], y=s["valeur"].rolling(lissage, min_periods=1).mean(),
                                                 name=f"{cap} lissé", line=dict(width=3)))
                        a, b, r2 = tendance(s)
                        x = (s["horodatage"] - s["horodatage"].min()).dt.total_seconds() / 86400
                        fig.add_trace(go.Scatter(x=s["horodatage"], y=a * x + b, name=f"{cap} tendance",
                                                 line=dict(dash="dash", width=2)))
                        unite, seuil = SEUILS.get(gr, ("", None))
                        if seuil:
                            fig.add_hline(y=seuil, line_dash="dot", line_color="#FF5C7A",
                                          annotation_text=f"Seuil {seuil} {unite}")
                            reste = jours_avant_seuil(s, seuil)
                            if reste is None:
                                msg = "pas de dérive croissante"
                            else:
                                msg = f"seuil atteint dans ≈ {reste:.0f} jours" if reste > 0 else "seuil déjà atteint"
                            st.caption(f"**{cap} · {gr}** — pente {a:+.4f} {unite}/jour, R² = {r2:.2f}, {msg}.")
                    st.plotly_chart(style_fig(fig, gr, 420))
            with tab2:
                z_max = st.slider("Sensibilité (écarts-types)", 2.0, 5.0, 3.0, 0.1)
                fen = st.slider("Fenêtre glissante", 6, 72, 24)
                res = []
                fig = go.Figure()
                for (cap, gr), s in sub.groupby(["capteur", "grandeur"]):
                    r = detecter_anomalies(s, fen, z_max)
                    fig.add_trace(go.Scatter(x=r["horodatage"], y=r["valeur"], mode="lines", name=f"{cap}", opacity=.7))
                    an = r[r["anomalie"]]
                    fig.add_trace(go.Scatter(x=an["horodatage"], y=an["valeur"], mode="markers", name=f"{cap} ⚠",
                                             marker=dict(size=11, symbol="x", color="#FF5C7A")))
                    res.append(an)
                st.plotly_chart(style_fig(fig, "Anomalies détectées", 420))
                tout = pd.concat(res) if res else pd.DataFrame()
                st.write(f"**{len(tout)}** anomalie(s).")
                if len(tout):
                    st.dataframe(tout[["horodatage", "ouvrage", "capteur", "grandeur", "valeur", "z"]].round(3))
            with tab3:
                piv = sub.pivot_table(index="horodatage", columns="capteur", values="valeur", aggfunc="mean")
                if piv.shape[1] < 2:
                    st.info("Sélectionnez au moins deux capteurs (ou deux grandeurs) pour calculer des corrélations.")
                else:
                    corr = piv.corr()
                    fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1,
                                               colorscale=[[0, "#FF4ECD"], [.5, "#111C3D"], [1, "#00D4FF"]],
                                               text=corr.round(2).values, texttemplate="%{text}"))
                    st.plotly_chart(style_fig(fig, "Matrice de corrélation", 460))
            with tab4:
                st.dataframe(statistiques(sub))
                fig = go.Figure()
                for cap, s in sub.groupby("capteur"):
                    fig.add_trace(go.Box(y=s["valeur"], name=cap))
                st.plotly_chart(style_fig(fig, "Distribution par capteur", 380))

# ============================================================================
# DIMENSIONNEMENT PONT
# ============================================================================
elif page.startswith("🌉"):
    st.title("Dimensionnement d'une poutre de pont")
    st.caption("Poutre en béton armé isostatique, flexion / cisaillement / flèche (méthode type Eurocode 2).")
    with st.sidebar.expander("Paramètres du pont", expanded=True):
        L = st.number_input("Portée L (m)", 3.0, 60.0, 18.0, 0.5)
        b = st.number_input("Largeur de poutre b (m)", 0.2, 3.0, 0.60, 0.05)
        h = st.number_input("Hauteur h (m)", 0.3, 4.0, 1.10, 0.05)
        fck = st.selectbox("Béton fck (MPa)", [25, 30, 35, 40, 45, 50], index=1)
        fyk = st.selectbox("Acier fyk (MPa)", [400, 500], index=1)
        enr = st.number_input("Enrobage (m)", 0.02, 0.10, 0.04, 0.005)
        diam = st.selectbox("Diamètre barres (mm)", [16, 20, 25, 32, 40], index=2)
        g_sup = st.number_input("Charges permanentes additionnelles (kN/m)", 0.0, 200.0, 15.0, 1.0)
        q = st.number_input("Charges d'exploitation (kN/m)", 0.0, 300.0, 30.0, 1.0)
        lim = st.selectbox("Limite de flèche", [250, 350, 500], index=0, format_func=lambda v: f"L/{v}")
    kw = dict(fck=fck, fyk=fyk, enrobage=enr, diam=diam, g_sup=g_sup, q=q, limite_fleche=lim)
    r = dimensionner_pont(L, b, h, **kw)

    ok_global = r.section_ok and r.cisaillement_ok and r.fleche_ok
    bandeau(ok_global, "Dimensionnement vérifié (flexion, effort tranchant, flèche)." if ok_global
            else "Une ou plusieurs vérifications ne sont pas satisfaites.")
    for m in r.messages:
        (st.info if m.startswith("Cadres") else st.warning)(m)

    c1, c2, c3, c4 = st.columns(4)
    with c1: carte("Moment M_Ed", f"{r.M_ed:,.0f} kN·m".replace(",", " "))
    with c2:
        carte("Effort tranchant V_Ed", f"{r.V_ed:,.0f} kN".replace(",", " "),
              "ok" if r.cisaillement_ok else "ko")
    with c3:
        carte("Armatures tendues", f"{r.n_barres} HA{r.diam}" if r.section_ok else "—",
              "ok" if r.section_ok else "ko")
    with c4: carte("Flèche ELS", f"{r.fleche:.1f} / {r.fleche_lim:.1f} mm", "ok" if r.fleche_ok else "ko")

    d1, d2 = st.columns(2)
    with d1:
        x, V, M = diagrammes_poutre(L, r.w_elu)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=M, fill="tozeroy", name="M (kN·m)", line=dict(color="#00D4FF", width=3),
                                 fillcolor="rgba(0,212,255,.25)"))
        fig.add_trace(go.Scatter(x=x, y=V, fill="tozeroy", name="V (kN)", line=dict(color="#FF4ECD", width=3),
                                 fillcolor="rgba(255,78,205,.2)"))
        st.plotly_chart(style_fig(fig, "Diagrammes M(x) et V(x) à l'ELU", 380))
    with d2:
        fig = go.Figure()
        fig.add_shape(type="rect", x0=0, y0=0, x1=b, y1=h, line=dict(color="#00D4FF", width=3),
                      fillcolor="rgba(123,97,255,.25)")
        if r.section_ok and r.n_barres:
            n = r.n_barres
            xs = np.linspace(enr + diam / 2000, b - enr - diam / 2000, max(n, 2))[:n] if n > 1 else [b / 2]
            fig.add_trace(go.Scatter(x=xs, y=[enr + diam / 2000] * len(xs), mode="markers",
                                     marker=dict(size=max(8, diam * 0.7), color="#FFC857",
                                                 line=dict(color="white", width=1)), name=f"{n} HA{diam}"))
        fig.update_xaxes(range=[-0.1 * b, 1.1 * b], scaleanchor="y", title="b (m)")
        fig.update_yaxes(range=[-0.05 * h, 1.05 * h], title="h (m)")
        st.plotly_chart(style_fig(fig, "Section transversale", 380))

    with st.expander("Détail des calculs"):
        st.dataframe(pd.DataFrame({
            "Grandeur": ["d utile (m)", "Charge ELU (kN/m)", "Charge ELS (kN/m)", "µ (limite 0,372)",
                         "As requise (cm²)", "As min (cm²)", "As fournie (cm²)", "V_Rd,c (kN)", "V_Rd,max (kN)", "Cadres (cm²/m)"],
            "Valeur": [round(r.d, 3), round(r.w_elu, 2), round(r.w_els, 2), round(r.mu, 3),
                       None if np.isnan(r.As_req) else round(r.As_req, 2), round(r.As_min, 2),
                       round(r.As_fournie, 2), round(r.V_rdc, 1), round(r.V_rdmax, 1),
                       round(r.asw_s, 2)]}))

    st.subheader("Optimisation")
    o1, o2 = st.columns(2)
    if o1.button("Trouver la hauteur minimale valide"):
        hmin = optimiser_hauteur(L, b, **kw)
        st.success(f"Hauteur minimale conforme : **{hmin} m** (L/h = {L / hmin:.1f})") if hmin else st.error(
            "Aucune hauteur ≤ 4 m ne convient : augmentez b ou fck.")
    hs = np.arange(0.4, 2.5, 0.05)
    fl = [dimensionner_pont(L, b, float(hh), **kw).fleche for hh in hs]
    fig = go.Figure(go.Scatter(x=hs, y=fl, line=dict(color="#7B61FF", width=3), name="Flèche"))
    fig.add_hline(y=L * 1000 / lim, line_dash="dash", line_color="#FF5C7A", annotation_text=f"L/{lim}")
    fig.update_xaxes(title="Hauteur h (m)")
    fig.update_yaxes(title="Flèche (mm)", type="log")
    st.plotly_chart(style_fig(fig, "Flèche en fonction de la hauteur", 340))

# ============================================================================
# DIMENSIONNEMENT SOUS-SOL
# ============================================================================
elif page.startswith("🕳️"):
    st.title("Dimensionnement de sous-sol")
    t1, t2, t3 = st.tabs(["🧱 Voile enterré", "🏗️ Semelle de fondation", "💧 Soulèvement (nappe)"])

    with st.sidebar.expander("Sol", expanded=True):
        gamma = st.number_input("Poids volumique γ (kN/m³)", 14.0, 24.0, 18.0, 0.5)
        phi = st.number_input("Angle de frottement φ (°)", 0.0, 45.0, 30.0, 1.0)
        c_sol = st.number_input("Cohésion c (kPa)", 0.0, 200.0, 0.0, 1.0)

    with t1:
        c1, c2, c3 = st.columns(3)
        H = c1.number_input("Hauteur enterrée H (m)", 1.0, 15.0, 4.0, 0.25)
        e = c2.number_input("Épaisseur du voile e (m)", 0.15, 1.2, 0.30, 0.05)
        qs = c3.number_input("Surcharge en surface (kPa)", 0.0, 100.0, 10.0, 1.0)
        c4, c5, c6 = st.columns(3)
        nappe_on = c4.checkbox("Nappe phréatique", value=False)
        zw = c5.number_input("Profondeur de la nappe (m)", 0.0, float(H), min(1.5, float(H)), 0.25,
                             disabled=not nappe_on)
        repos = c6.radio("Poussée", ["Au repos (K0)", "Active (Ka)"]) .startswith("Au")
        rv = dimensionner_voile(H, e, gamma, phi, qs, zw if nappe_on else None, repos)
        bandeau(rv.epaisseur_ok, "Épaisseur suffisante en flexion." if rv.epaisseur_ok
                else "Épaisseur insuffisante : augmentez e.")
        a1, a2, a3, a4 = st.columns(4)
        with a1: carte("Coefficient K", f"{rv.K:.3f}")
        with a2: carte("Poussée totale", f"{rv.force:.1f} kN/m")
        with a3: carte("Moment d'encastrement", f"{rv.M_base:.1f} kN·m/m")
        with a4:
            carte("As requise", "—" if not rv.epaisseur_ok else f"{max(rv.As_req, rv.As_min):.1f} cm²/m",
                  "ok" if rv.epaisseur_ok else "ko")
        fig = go.Figure(go.Scatter(x=rv.p, y=rv.z, fill="tozerox", line=dict(color="#00D4FF", width=3),
                                   fillcolor="rgba(0,212,255,.25)", name="Pression"))
        if nappe_on:
            fig.add_hline(y=zw, line_dash="dash", line_color="#5CB8FF", annotation_text="Nappe")
        fig.update_yaxes(autorange="reversed", title="Profondeur z (m)")
        fig.update_xaxes(title="Pression horizontale (kPa)")
        st.plotly_chart(style_fig(fig, "Diagramme de poussée sur le voile", 440))

    with t2:
        c1, c2, c3 = st.columns(3)
        B = c1.number_input("Largeur B (m)", 0.5, 10.0, 2.0, 0.1)
        Lf = c2.number_input("Longueur L (m)", 0.5, 20.0, 2.0, 0.1)
        D = c3.number_input("Encastrement D (m)", 0.0, 10.0, 1.5, 0.1)
        c4, c5, c6 = st.columns(3)
        N = c4.number_input("Charge de service N (kN)", 10.0, 50000.0, 900.0, 10.0)
        E = c5.number_input("Module du sol E (kPa)", 1000.0, 200000.0, 25000.0, 1000.0)
        FS = c6.number_input("Coefficient de sécurité", 1.5, 5.0, 3.0, 0.1)
        rs = capacite_portante(B, max(Lf, B), N, D, gamma, phi, c_sol, E, FS=FS)
        bandeau(rs.portance_ok and rs.tassement_ok,
                "Portance et tassement acceptables." if rs.portance_ok and rs.tassement_ok
                else "Portance ou tassement non conforme.")
        a1, a2, a3, a4 = st.columns(4)
        with a1: carte("q ultime", f"{rs.q_ultime:.0f} kPa")
        with a2: carte("q admissible", f"{rs.q_adm:.0f} kPa")
        with a3: carte("q appliquée", f"{rs.q_appliquee:.0f} kPa", "ok" if rs.portance_ok else "ko")
        with a4: carte("Tassement", f"{rs.tassement_mm:.1f} mm", "ok" if rs.tassement_ok else "ko")
        fig = go.Figure(go.Indicator(mode="gauge+number", value=rs.taux * 100,
                                     number={"suffix": " %"}, title={"text": "Taux de travail du sol"},
                                     gauge={"axis": {"range": [0, 150]}, "bar": {"color": "#7B61FF"},
                                            "steps": [{"range": [0, 80], "color": "rgba(46,242,160,.35)"},
                                                      {"range": [80, 100], "color": "rgba(255,200,87,.4)"},
                                                      {"range": [100, 150], "color": "rgba(255,92,122,.45)"}]}))
        st.plotly_chart(style_fig(fig, "", 320))

    with t3:
        c1, c2, c3 = st.columns(3)
        A = c1.number_input("Aire du sous-sol (m²)", 10.0, 20000.0, 400.0, 10.0)
        W = c2.number_input("Poids total de la structure (kN)", 100.0, 500000.0, 30000.0, 100.0)
        hw = c3.number_input("Hauteur d'eau sous le radier (m)", 0.0, 15.0, 3.0, 0.25)
        rf = verif_soulevement(W, A, hw)
        bandeau(rf.ok, f"Coefficient de sécurité au soulèvement = {rf.FS:.2f} (minimum 1,10)" if rf.FS != float("inf")
                else "Pas de poussée d'eau : aucun risque de soulèvement.")
        a1, a2, a3 = st.columns(3)
        with a1: carte("Poids stabilisateur", f"{rf.poids:,.0f} kN".replace(",", " "))
        with a2: carte("Poussée d'Archimède", f"{rf.poussee:,.0f} kN".replace(",", " "), "ko" if not rf.ok else "ok")
        with a3: carte("Lest supplémentaire", f"{rf.lest_requis:,.0f} kN".replace(",", " "), "ko" if rf.lest_requis else "ok")

st.sidebar.caption("v1.0 — données stockées localement (SQLite)")

# ============================================================================
# EXPORT
# ============================================================================
if page.startswith("📤"):
    st.title("Export des résultats")
    if df.empty:
        st.warning("Aucune donnée à exporter.")
    else:
        alertes = etat_alertes(df)
        st.write("Le classeur Excel contient les mesures brutes, les statistiques et l'état des alertes.")
        xls = vers_excel({"Mesures": df, "Statistiques": statistiques(df), "Alertes": alertes})
        c1, c2 = st.columns(2)
        c1.download_button("📗 Télécharger Excel", xls, "rapport_chantier.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        c2.download_button("📄 Télécharger CSV", df.to_csv(index=False).encode("utf-8"),
                           "mesures.csv", "text/csv")
        st.dataframe(alertes)
