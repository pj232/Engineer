#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APPLICATION STREAMLIT - DIMENSIONNEMENT PRELIMINAIRE D'UN BATIMENT BA (R+n)
Dalles, poutres, poteaux, semelles, quantitatifs. Eurocodes (methode simplifiee).

Installation :   pip install streamlit pandas
Lancement    :   streamlit run app.py      (dans le terminal de PyCharm)

!!! Outil de pre-dimensionnement : a valider par un ingenieur structure !!!
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# 1. DONNEES D'ENTREE
# --------------------------------------------------------------------------
Q_USAGE = {  # charges d'exploitation EC1 (kN/m2)
    "habitation": 2.0,
    "bureaux": 3.0,
    "commerce": 5.0,
    "parking": 2.5,
}
GAMMA_BA = 25.0  # poids volumique beton arme (kN/m3)
ACIER_RHO = 7850.0  # kg/m3


@dataclass
class Materiaux:
    fck: float = 25.0       # MPa (C25/30)
    fyk: float = 500.0      # MPa (HA500)
    gamma_c: float = 1.5
    gamma_s: float = 1.15

    @property
    def fcd(self) -> float:
        return self.fck / self.gamma_c

    @property
    def fyd(self) -> float:
        return self.fyk / self.gamma_s

    @property
    def fctm(self) -> float:
        return 0.30 * self.fck ** (2.0 / 3.0)


@dataclass
class Projet:
    nom: str = "Immeuble R+10"
    nb_etages: int = 10              # R+10 -> 11 niveaux de plancher
    hauteur_etage: float = 3.0       # m
    hauteur_rdc: float = 3.5         # m
    portee_x: float = 5.0            # m (entre axes de poteaux)
    portee_y: float = 5.0            # m
    nb_travees_x: int = 4
    nb_travees_y: int = 3
    usage: str = "habitation"
    g_revetement: float = 1.5        # kN/m2 (chape + carrelage + enduit)
    g_cloisons: float = 1.0          # kN/m2 (cloisons reparties)
    g_toiture: float = 2.0           # kN/m2 (etancheite + protection)
    q_toiture: float = 1.5           # kN/m2 (terrasse accessible)
    g_facade: float = 6.0            # kN/ml (facade / maconnerie de rive)
    sigma_sol: float = 200.0         # kPa (contrainte admissible du sol)
    coef_flambement: float = 0.7     # l0 = coef * hauteur libre (portique contreventé)
    rho_max_poteau: float = 0.03     # taux d'acier max cible dans les poteaux
    materiaux: Materiaux = field(default_factory=Materiaux)

    @property
    def n_niveaux(self) -> int:
        return self.nb_etages + 1

    @property
    def q_plancher(self) -> float:
        return Q_USAGE[self.usage]

    @property
    def psi0(self) -> float:
        return 0.7


def charger_config(chemin: str) -> Projet:
    cfg = json.loads(Path(chemin).read_text(encoding="utf-8"))
    mat = Materiaux(**cfg.pop("materiaux", {}))
    return Projet(materiaux=mat, **cfg)


def saisie_interactive() -> Projet:
    """Collecte des donnees au clavier (Entree = valeur par defaut)."""
    p = Projet()

    def ask(label, default, typ=float):
        rep = input(f"{label} [{default}] : ").strip()
        return typ(rep) if rep else default

    print("=== Collecte des donnees du projet (Entree = valeur par defaut) ===")
    p.nom = ask("Nom du projet", p.nom, str)
    p.nb_etages = ask("Nombre d'etages (R+n -> n)", p.nb_etages, int)
    p.hauteur_etage = ask("Hauteur d'etage (m)", p.hauteur_etage)
    p.hauteur_rdc = ask("Hauteur RDC (m)", p.hauteur_rdc)
    p.portee_x = ask("Portee en X (m)", p.portee_x)
    p.portee_y = ask("Portee en Y (m)", p.portee_y)
    p.nb_travees_x = ask("Nombre de travees en X", p.nb_travees_x, int)
    p.nb_travees_y = ask("Nombre de travees en Y", p.nb_travees_y, int)
    p.usage = ask(f"Usage {list(Q_USAGE)}", p.usage, str)
    p.sigma_sol = ask("Contrainte admissible du sol (kPa)", p.sigma_sol)
    p.materiaux.fck = ask("fck beton (MPa)", p.materiaux.fck)
    p.materiaux.fyk = ask("fyk acier (MPa)", p.materiaux.fyk)
    return p


# --------------------------------------------------------------------------
# 2. OUTILS DE CALCUL
# --------------------------------------------------------------------------
def arrondi_sup(x: float, pas: float = 0.05) -> float:
    return round(math.ceil(x / pas - 1e-9) * pas, 3)


MU_LIM = 0.295  # x/d <= 0.45 (ductilite) -> pas d'aciers comprimes en dessous


def flexion(M_kNm: float, b: float, d: float, dp: float, mat: Materiaux):
    """Section rectangulaire ELU. Retourne (As, As', mu) en cm2."""
    M = abs(M_kNm) / 1000.0  # MN.m
    mu = M / (b * d * d * mat.fcd)
    if mu > 0.45:
        raise ValueError(f"Section insuffisante (mu={mu:.2f}) : augmenter b ou h")
    if mu <= MU_LIM:
        z = 0.5 * d * (1 + math.sqrt(1 - 2 * mu))
        return M / (z * mat.fyd) * 1e4, 0.0, mu
    zl = 0.5 * d * (1 + math.sqrt(1 - 2 * MU_LIM))
    Ml = MU_LIM * b * d * d * mat.fcd
    dM = M - Ml
    Asc = dM / ((d - dp) * mat.fyd) * 1e4
    As = Ml / (zl * mat.fyd) * 1e4 + Asc
    return As, Asc, mu


def as_min_flexion(b: float, d: float, mat: Materiaux) -> float:
    return max(0.26 * mat.fctm / mat.fyk, 0.0013) * b * d * 1e4  # cm2


def aire_barre(phi_mm: float) -> float:
    return math.pi * phi_mm ** 2 / 4.0 / 100.0  # cm2


def barres_dalle(As_req: float, h: float):
    """Treillis par metre : cherche HA phi / espacement."""
    esp_max = min(3 * h, 0.40) * 1000
    for phi in (8, 10, 12, 14, 16):
        for e in (250, 200, 150, 125, 100):
            if e > esp_max:
                continue
            a = aire_barre(phi) * 1000.0 / e
            if a >= As_req:
                return f"HA{phi} e={e/10:.1f}cm", a
    return "A revoir (augmenter l'epaisseur)", 0.0


def barres_poutre(As_req: float, b: float):
    best = None
    for phi in (12, 14, 16, 20, 25, 32):
        nmax1 = int((b * 1000 - 2 * (30 + 8) + 25) // (phi + 25))
        for n in range(2, 2 * max(nmax1, 2) + 1):
            a = n * aire_barre(phi)
            if a >= As_req:
                lits = 1 if n <= nmax1 else 2
                cand = (a, n, phi, lits)
                if best is None or a < best[0]:
                    best = cand
                break
    if not best:
        return "A revoir (augmenter la section)", 0.0
    a, n, phi, lits = best
    return f"{n}HA{phi}" + (" (2 lits)" if lits == 2 else ""), a


def barres_poteau(As_req: float, c: float):
    best = None
    nmax = 4 * max(1, int((c - 0.10) / 0.10) + 1)
    for n in (4, 6, 8, 10, 12, 16, 20):
        if n > nmax:
            continue
        for phi in (12, 14, 16, 20, 25, 32):
            a = n * aire_barre(phi)
            if a >= As_req and (best is None or a < best[0]):
                best = (a, n, phi)
    if not best:
        return "A revoir", 0.0, 0
    return f"{best[1]}HA{best[2]}", best[0], best[2]


# --------------------------------------------------------------------------
# 3. DALLES
# --------------------------------------------------------------------------
def dimensionner_dalle(p: Projet) -> dict:
    mat = p.materiaux
    lx, ly = sorted((p.portee_x, p.portee_y))
    alpha = lx / ly
    h = max(0.15, arrondi_sup(lx / 35.0, 0.01))
    enrob, phi = 0.025, 0.010
    d = h - enrob - phi / 2
    g = GAMMA_BA * h + p.g_revetement + p.g_cloisons
    q = p.q_plancher
    pu = 1.35 * g + 1.5 * q
    pser = g + q

    if alpha >= 0.4:  # porte dans 2 sens (BAEL, nu=0)
        mux = 1.0 / (8 * (1 + 2.4 * alpha ** 3))
        muy = alpha ** 2 * (1 - 0.95 * (1 - alpha) ** 2)
        Mx0 = mux * pu * lx ** 2
        My0 = muy * Mx0
        sens = "2 sens"
    else:             # porte dans 1 sens
        Mx0 = pu * lx ** 2 / 8
        My0 = Mx0 / 4
        sens = "1 sens"

    Mtx, Mty, Ma = 0.75 * Mx0, 0.75 * My0, 0.5 * Mx0
    amin = as_min_flexion(1.0, d, mat)
    res = {"h": h, "d": d, "g": g, "q": q, "pu": pu, "pser": pser, "alpha": alpha,
           "fonctionnement": sens, "Mtx": Mtx, "Mty": Mty, "Ma": Ma}
    for cle, M in (("travee_x", Mtx), ("travee_y", Mty), ("appui", Ma)):
        As, _, mu = flexion(M, 1.0, d, enrob + phi / 2, mat)
        As = max(As, amin)
        txt, prov = barres_dalle(As, h)
        res[cle] = {"As_req_cm2_m": As, "armature": txt, "As_prov_cm2_m": prov, "mu": mu}
    res["acier_kg_m2"] = (res["travee_x"]["As_prov_cm2_m"] + res["travee_y"]["As_prov_cm2_m"]
                          + 0.6 * res["appui"]["As_prov_cm2_m"]) * 1e-4 * ACIER_RHO * 1.10
    return res


# --------------------------------------------------------------------------
# 4. POUTRES
# --------------------------------------------------------------------------
def dimensionner_poutre(p: Projet, dalle: dict) -> dict:
    mat = p.materiaux
    lx, ly = sorted((p.portee_x, p.portee_y))
    L = ly                                   # poutre la plus longue (cas defavorable)
    hs = dalle["h"]
    h = arrondi_sup(L / 12.0)
    b = max(0.25, arrondi_sup(0.4 * h))
    d = h - 0.04
    alpha = lx / ly
    pu_dalle = dalle["pu"]
    p_dalle = pu_dalle * lx * (1 - alpha ** 2 / 3.0)       # 2 trapezes de chaque cote
    p_pp = 1.35 * GAMMA_BA * b * (h - hs)
    pu = p_dalle + p_pp
    M0 = pu * L ** 2 / 8
    Mt, Ma = 0.80 * M0, 0.60 * M0
    V = 0.6 * pu * L

    res = {"L": L, "b": b, "h": h, "d": d, "pu_kN_m": pu, "Mt": Mt, "Ma": Ma, "VEd": V}
    amin = as_min_flexion(b, d, mat)
    for cle, M in (("travee", Mt), ("appui", Ma)):
        As, Asc, mu = flexion(M, b, d, 0.04, mat)
        As = max(As, amin)
        txt, prov = barres_poutre(As, b)
        r = {"As_req_cm2": As, "armature": txt, "As_prov_cm2": prov, "mu": mu}
        if Asc > 0:
            r["As_comprimes_cm2"] = Asc
        res[cle] = r

    # Effort tranchant (EC2 6.2.3, bielles inclinees)
    z = 0.9 * d
    nu = 0.6 * (1 - mat.fck / 250.0)
    fywd = mat.fyd
    m = (V / 1000.0) / (b * z * nu * mat.fcd)
    if 1.0 / m < 2.0:
        res["cisaillement"] = {"statut": "NON OK : augmenter b ou h"}
    else:
        cot = min(2.5, (1.0 / m + math.sqrt(max(1.0 / m ** 2 - 4, 0))) / 2)
        asw_s = (V / 1000.0) / (z * fywd * cot) * 1e4  # cm2/m
        rho_min = 0.08 * math.sqrt(mat.fck) / mat.fyk
        asw_s = max(asw_s, rho_min * b * 100 * 100)
        a_cadre = 2 * aire_barre(8)
        s = min(a_cadre / asw_s * 100, 0.75 * d * 100, 30.0)  # cm
        s = max(5.0, math.floor(s / 2.5) * 2.5)
        res["cisaillement"] = {"statut": "OK", "cot_theta": cot,
                               "Asw_s_cm2_m": asw_s, "cadres": f"HA8 e={s:.1f}cm"}
    return res


# --------------------------------------------------------------------------
# 5. POTEAUX : DESCENTE DE CHARGES + DIMENSIONNEMENT
# --------------------------------------------------------------------------
def coef_flambement(lam: float) -> float:
    if lam <= 50:
        return 0.85 / (1 + 0.2 * (lam / 35.0) ** 2)
    return 0.60 * (50.0 / lam) ** 2


def dimensionner_poteaux(p: Projet, dalle: dict, poutre: dict) -> dict:
    mat = p.materiaux
    Lx, Ly = p.portee_x, p.portee_y
    n = p.n_niveaux
    hs = dalle["h"]
    g_poutre = GAMMA_BA * poutre["b"] * (poutre["h"] - hs)  # kN/ml
    types = {  # aire, longueur de poutre reprise, longueur de facade
        "centrale": (Lx * Ly, Lx + Ly, 0.0),
        "rive": (Lx * Ly / 2, Lx + Ly / 2, Lx),
        "angle": (Lx * Ly / 4, (Lx + Ly) / 2, (Lx + Ly) / 2),
    }
    out = {}
    for nom, (A, Lp, Lf) in types.items():
        G_cur = 0.0           # permanentes cumulees (planchers+poutres+facades)
        Q_etage = 0.0         # exploitation non reduite cumulee
        n_q = 0
        Gcol_above = 0.0
        c_prev = 0.25
        niveaux = []
        for j in range(n, 0, -1):          # j = n (dernier niveau) ... 1 (RDC)
            toit = (j == n)
            if toit:
                G_slab = (GAMMA_BA * hs + p.g_toiture) * A + g_poutre * Lp + 0.5 * p.g_facade * Lf
                Q_toit = p.q_toiture * A
            else:
                G_slab = (GAMMA_BA * hs + p.g_revetement + p.g_cloisons) * A \
                    + g_poutre * Lp + p.g_facade * Lf
                Q_etage += p.q_plancher * A
                n_q += 1
            G_cur += G_slab
            Q_toit_val = p.q_toiture * A
            alpha_n = 1.0 if n_q <= 2 else (2 + (n_q - 2) * p.psi0) / n_q   # EC1 6.3.1.2
            Q_red = alpha_n * Q_etage
            h_et = p.hauteur_rdc if j == 1 else p.hauteur_etage

            c = max(0.25, c_prev)
            while True:
                Ac = c * c
                w = GAMMA_BA * Ac * h_et
                G_tot = G_cur + Gcol_above + w
                N_ed = 1.35 * G_tot + 1.5 * (Q_red + Q_toit_val)
                N_ser = G_tot + Q_red + Q_toit_val
                lam = p.coef_flambement * (h_et - poutre["h"]) / (c / math.sqrt(12))
                alpha = coef_flambement(lam)
                As_req = (N_ed / 1000.0 / alpha - Ac * mat.fcd) / mat.fyd * 1e4
                As_min = max(0.10 * N_ed / 1000.0 / mat.fyd * 1e4, 0.002 * Ac * 1e4)
                As = max(As_req, As_min)
                txt, prov, phi = barres_poteau(As, c)
                if (prov > 0 and prov <= p.rho_max_poteau * Ac * 1e4) or c >= 1.5:
                    break
                c = round(c + 0.05, 2)
            phi_t = max(6, 8 if phi <= 20 else 10)
            esp = min(20 * phi, c * 1000, 400) / 10
            niveaux.append({
                "niveau": j, "section_m": f"{c:.2f}x{c:.2f}", "c": c,
                "N_ed_kN": N_ed, "N_ser_kN": N_ser, "elancement": lam,
                "alpha": alpha, "As_req_cm2": As, "armature": txt,
                "As_prov_cm2": prov, "taux_acier_%": 100 * prov / (Ac * 1e4),
                "cadres": f"HA{phi_t} e={esp:.0f}cm",
                "statut": "OK" if prov >= As else "A REVOIR",
            })
            Gcol_above += w
            c_prev = c
        out[nom] = sorted(niveaux, key=lambda r: r["niveau"])
    return out


# --------------------------------------------------------------------------
# 6. FONDATIONS (semelles isolees) + QUANTITATIFS
# --------------------------------------------------------------------------
def dimensionner_fondations(p: Projet, poteaux: dict) -> dict:
    out = {}
    total_surface = 0.0
    nx, ny = p.nb_travees_x, p.nb_travees_y
    nb = {"angle": 4, "rive": 2 * (nx - 1) + 2 * (ny - 1), "centrale": (nx - 1) * (ny - 1)}
    for nom, niv in poteaux.items():
        base = niv[0]
        A = 1.10 * base["N_ser_kN"] / p.sigma_sol
        B = arrondi_sup(math.sqrt(A), 0.05)
        h = max(0.40, arrondi_sup((B - base["c"]) / 4 + 0.05, 0.05))
        out[nom] = {"nombre": nb[nom], "N_ser_kN": base["N_ser_kN"],
                    "B_m": B, "h_m": h, "sigma_reelle_kPa": 1.10 * base["N_ser_kN"] / B ** 2}
        total_surface += nb[nom] * B * B
    emprise = nx * p.portee_x * ny * p.portee_y
    out["taux_occupation"] = total_surface / emprise
    out["recommandation"] = (
        "Semelles isolees envisageables." if out["taux_occupation"] < 0.5 else
        "Taux d'occupation > 50 % : prevoir radier general ou fondations profondes (pieux)."
    )
    return out


def quantitatifs(p: Projet, dalle, poutre, poteaux) -> dict:
    nx, ny = p.nb_travees_x, p.nb_travees_y
    emprise = nx * p.portee_x * ny * p.portee_y
    n = p.n_niveaux
    v_dalle = dalle["h"] * emprise * n
    nb_poutres_lin = (ny + 1) * nx * p.portee_x + (nx + 1) * ny * p.portee_y
    v_poutre = poutre["b"] * (poutre["h"] - dalle["h"]) * nb_poutres_lin * n
    nb = {"angle": 4, "rive": 2 * (nx - 1) + 2 * (ny - 1), "centrale": (nx - 1) * (ny - 1)}
    v_poteau, acier_poteau = 0.0, 0.0
    for nom, niv in poteaux.items():
        for r in niv:
            h = p.hauteur_rdc if r["niveau"] == 1 else p.hauteur_etage
            v_poteau += nb[nom] * r["c"] ** 2 * h
            acier_poteau += nb[nom] * r["As_prov_cm2"] * 1e-4 * h * ACIER_RHO
    acier_dalle = dalle["acier_kg_m2"] * emprise * n
    acier_poutre = 110.0 * v_poutre  # ratio forfaitaire kg/m3
    v_tot = v_dalle + v_poutre + v_poteau
    a_tot = acier_dalle + acier_poutre + acier_poteau
    return {"emprise_m2": emprise, "surface_planchers_m2": emprise * n,
            "beton_dalles_m3": v_dalle, "beton_poutres_m3": v_poutre,
            "beton_poteaux_m3": v_poteau, "beton_total_m3": v_tot,
            "acier_total_kg(estime)": a_tot, "ratio_acier_kg_m3": a_tot / v_tot,
            "beton_m3_par_m2_plancher": v_tot / (emprise * n)}


# --------------------------------------------------------------------------
# 7. ORCHESTRATION, RAPPORT, EXPORT
# --------------------------------------------------------------------------
def dimensionner(p: Projet) -> dict:
    dalle = dimensionner_dalle(p)
    poutre = dimensionner_poutre(p, dalle)
    poteaux = dimensionner_poteaux(p, dalle, poutre)
    fond = dimensionner_fondations(p, poteaux)
    quant = quantitatifs(p, dalle, poutre, poteaux)
    return {"projet": asdict(p), "dalle": dalle, "poutre": poutre,
            "poteaux": poteaux, "fondations": fond, "quantitatifs": quant}


def rapport(res: dict) -> str:
    p, d, b = res["projet"], res["dalle"], res["poutre"]
    L = []
    add = L.append
    add("=" * 72)
    add(f" NOTE DE PRE-DIMENSIONNEMENT - {p['nom']}")
    add(f" R+{p['nb_etages']} | {p['nb_travees_x']}x{p['portee_x']} m  par  "
        f"{p['nb_travees_y']}x{p['portee_y']} m | usage : {p['usage']}")
    m = p["materiaux"]
    add(f" Beton C{m['fck']:.0f} | Acier HA{m['fyk']:.0f} | sol : {p['sigma_sol']:.0f} kPa")
    add("=" * 72)
    add("\n1) DALLES (plancher courant)")
    add(f"   Epaisseur h = {d['h']*100:.0f} cm | G = {d['g']:.2f} kPa | Q = {d['q']:.2f} kPa "
        f"| pu = {d['pu']:.2f} kPa | {d['fonctionnement']}")
    add(f"   Travee X : {d['travee_x']['armature']}  (As req {d['travee_x']['As_req_cm2_m']:.2f} cm2/m)")
    add(f"   Travee Y : {d['travee_y']['armature']}  (As req {d['travee_y']['As_req_cm2_m']:.2f} cm2/m)")
    add(f"   Appuis   : {d['appui']['armature']}  (As req {d['appui']['As_req_cm2_m']:.2f} cm2/m)")
    add("\n2) POUTRES (poutre la plus longue)")
    add(f"   Section {b['b']*100:.0f} x {b['h']*100:.0f} cm | L = {b['L']} m | pu = {b['pu_kN_m']:.1f} kN/m")
    add(f"   Mt = {b['Mt']:.1f} kN.m -> {b['travee']['armature']}  (As req {b['travee']['As_req_cm2']:.2f} cm2)")
    add(f"   Ma = {b['Ma']:.1f} kN.m -> {b['appui']['armature']}  (As req {b['appui']['As_req_cm2']:.2f} cm2)")
    cs = b["cisaillement"]
    add(f"   VEd = {b['VEd']:.1f} kN -> " + (f"cadres {cs['cadres']}" if cs["statut"] == "OK" else cs["statut"]))
    add("\n3) POTEAUX (section par niveau, de bas en haut)")
    for nom, niv in res["poteaux"].items():
        add(f"   -- Poteau {nom} --")
        add("   Niv | Section  |  NEd (kN) | lambda | As req | Armature  | taux % | Cadres")
        for r in niv:
            add(f"   {r['niveau']:>3} | {r['section_m']:<8} | {r['N_ed_kN']:>9.0f} | "
                f"{r['elancement']:>6.1f} | {r['As_req_cm2']:>6.1f} | {r['armature']:<9} | "
                f"{r['taux_acier_%']:>5.2f}  | {r['cadres']}"
                + ("" if r["statut"] == "OK" else "  <-- A REVOIR"))
    add("\n4) FONDATIONS (semelles isolees)")
    f = res["fondations"]
    for nom in ("centrale", "rive", "angle"):
        s = f[nom]
        add(f"   {nom:<9}: {s['nombre']:>2} u | N_ser = {s['N_ser_kN']:.0f} kN | "
            f"{s['B_m']:.2f} x {s['B_m']:.2f} x {s['h_m']:.2f} m | sigma = {s['sigma_reelle_kPa']:.0f} kPa")
    add(f"   Taux d'occupation : {f['taux_occupation']*100:.0f} % -> {f['recommandation']}")
    q = res["quantitatifs"]
    add("\n5) QUANTITATIFS ESTIMES")
    add(f"   Beton : {q['beton_total_m3']:.0f} m3 (dalles {q['beton_dalles_m3']:.0f}, "
        f"poutres {q['beton_poutres_m3']:.0f}, poteaux {q['beton_poteaux_m3']:.0f})")
    add(f"   Acier : {q['acier_total_kg(estime)']/1000:.1f} t  ({q['ratio_acier_kg_m3']:.0f} kg/m3)")
    add("\nNON PRIS EN COMPTE : vent, seisme, noyau/voiles de contreventement, poinconnement,")
    add("fleches, fissuration, fondations reelles. A completer par une note de calcul complete.")
    return "\n".join(L)


def exporter(res: dict, dossier: str) -> None:
    out = Path(dossier)
    out.mkdir(parents=True, exist_ok=True)
    (out / "resultats.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "rapport.txt").write_text(rapport(res), encoding="utf-8")
    with open(out / "poteaux.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["type", "niveau", "section_m", "N_ed_kN", "N_ser_kN", "elancement",
                    "As_req_cm2", "armature", "taux_acier_%", "cadres", "statut"])
        for nom, niv in res["poteaux"].items():
            for r in niv:
                w.writerow([nom, r["niveau"], r["section_m"], round(r["N_ed_kN"], 1),
                            round(r["N_ser_kN"], 1), round(r["elancement"], 1),
                            round(r["As_req_cm2"], 2), r["armature"],
                            round(r["taux_acier_%"], 2), r["cadres"], r["statut"]])


# ==========================================================================
# 8. INTERFACE STREAMLIT
# ==========================================================================
import io

import pandas as pd
import streamlit as st


# --- Palette vive : indigo / cyan / ambre / emeraude -----------------------
SOMBRE, VIOLET, AMBRE, CLAIR, CYAN = "#1E1B4B", "#4F46E5", "#F59E0B", "#EEF2FF", "#06B6D4"
VERT, ROUGE = "#10B981", "#EF4444"

CSS = f"""
<style>
.stApp {{ background: linear-gradient(180deg, #F8FAFF 0%, #FFFFFF 40%); }}
.block-container {{ padding-top: 1.4rem; max-width: 1250px; }}
h2, h3 {{ color: {SOMBRE}; font-weight: 800; letter-spacing: -0.01em; }}
.hero {{
  background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 45%, #06B6D4 100%);
  border-radius: 20px; padding: 30px 36px; margin-bottom: 22px;
  box-shadow: 0 14px 34px rgba(79,70,229,.35); position: relative; overflow: hidden;
}}
.hero::after {{ content:""; position:absolute; right:-60px; top:-60px; width:220px; height:220px;
  background: radial-gradient(circle, rgba(255,255,255,.28), transparent 70%); border-radius:50%; }}
.hero h1 {{ color: #fff; margin: 0; font-size: 2.1rem; font-weight: 800; }}
.hero p  {{ color: #E0E7FF; margin: 8px 0 0 0; font-size: 1rem; }}
.hero .tag {{ display:inline-block; background:{AMBRE}; color:{SOMBRE}; font-weight:800;
  font-size:.75rem; padding:4px 12px; border-radius:20px; margin-bottom:12px; letter-spacing:.06em; }}
[data-testid="stMetric"] {{
  border-radius: 16px; padding: 16px 20px; color: #fff;
  box-shadow: 0 8px 20px rgba(30,27,75,.18); border: none;
  background: linear-gradient(135deg, #4F46E5, #7C3AED);
}}
[data-testid="stHorizontalBlock"] > div:nth-child(2) [data-testid="stMetric"] {{ background: linear-gradient(135deg, #0891B2, #06B6D4); }}
[data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stMetric"] {{ background: linear-gradient(135deg, #F59E0B, #F97316); }}
[data-testid="stHorizontalBlock"] > div:nth-child(4) [data-testid="stMetric"] {{ background: linear-gradient(135deg, #059669, #10B981); }}
[data-testid="stMetricLabel"] p {{ color: rgba(255,255,255,.88) !important; font-weight: 600; }}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] div {{ color: #fff !important; font-weight: 800; }}
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, #EEF2FF 0%, #E0F2FE 100%); border-right: 4px solid {VIOLET}; }}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ color: {VIOLET}; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 8px; border-bottom: none; }}
.stTabs [data-baseweb="tab"] {{
  background: {CLAIR}; border-radius: 999px; padding: 8px 20px; color: {SOMBRE}; font-weight: 700;
}}
.stTabs [aria-selected="true"] {{ background: linear-gradient(120deg, #4F46E5, #7C3AED); color: #fff !important; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}
.stDownloadButton button {{
  background: linear-gradient(120deg, #4F46E5, #06B6D4); color: #fff; border: none;
  border-radius: 12px; font-weight: 700; padding: 8px 18px;
}}
.stDownloadButton button:hover {{ background: linear-gradient(120deg, #F59E0B, #F97316); color: #fff; }}
[data-testid="stDataFrame"] {{ border: 2px solid #E0E7FF; border-radius: 14px; overflow: hidden; }}
.carte {{ background: linear-gradient(120deg, #EEF2FF, #ECFEFF); border-left: 6px solid {VIOLET};
  border-radius: 12px; padding: 14px 18px; margin: 6px 0 12px 0; color: {SOMBRE}; }}
</style>
"""


def appliquer_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def style_statut(df: pd.DataFrame, col: str = "statut"):
    """Badge vert/rouge sur la colonne de statut + barre orange sur le taux d'acier."""
    sty = df.style.map(
        lambda v: (f"background-color:{VERT}22;color:{VERT};font-weight:700" if v == "OK"
                   else f"background-color:{ROUGE}22;color:{ROUGE};font-weight:700"),
        subset=[col])
    if "taux_acier_%" in df.columns:
        sty = sty.bar(subset=["taux_acier_%"], color="#FCD34D", vmin=0, vmax=4)
    return sty.format(precision=2)


def interface() -> None:
    st.set_page_config(page_title="Dimensionnement bâtiment BA", page_icon="🏢", layout="wide")
    appliquer_style()
    st.markdown(
        """<div class="hero"><span class="tag">GÉNIE CIVIL · BÉTON ARMÉ</span>
        <h1>🏢 Dimensionnement d'un bâtiment R+n</h1>
        <p>Dalles · Poutres · Poteaux · Fondations — Eurocodes (méthode simplifiée).
        Outil de pré-dimensionnement, à valider par un ingénieur structure.</p></div>""",
        unsafe_allow_html=True)

    d = Projet()
    with st.sidebar:
        st.header("📥 Données du projet")
        nom = st.text_input("Nom du projet", d.nom)
        st.subheader("Géométrie")
        nb_etages = st.number_input("Nombre d'étages (R+n)", 1, 40, d.nb_etages)
        h_et = st.number_input("Hauteur d'étage (m)", 2.5, 5.0, d.hauteur_etage, 0.1)
        h_rdc = st.number_input("Hauteur RDC (m)", 2.5, 6.0, d.hauteur_rdc, 0.1)
        px = st.number_input("Portée en X (m)", 3.0, 10.0, d.portee_x, 0.1)
        py = st.number_input("Portée en Y (m)", 3.0, 10.0, d.portee_y, 0.1)
        nx = st.number_input("Nombre de travées en X", 1, 15, d.nb_travees_x)
        ny = st.number_input("Nombre de travées en Y", 1, 15, d.nb_travees_y)
        st.subheader("Charges")
        usage = st.selectbox("Usage", list(Q_USAGE), index=0)
        g_rev = st.number_input("Revêtement G (kN/m²)", 0.0, 5.0, d.g_revetement, 0.1)
        g_cl = st.number_input("Cloisons G (kN/m²)", 0.0, 5.0, d.g_cloisons, 0.1)
        g_toit = st.number_input("Toiture G (kN/m²)", 0.0, 6.0, d.g_toiture, 0.1)
        q_toit = st.number_input("Toiture Q (kN/m²)", 0.0, 5.0, d.q_toiture, 0.1)
        g_fac = st.number_input("Façade (kN/ml)", 0.0, 20.0, d.g_facade, 0.5)
        st.subheader("Matériaux et sol")
        fck = st.selectbox("Béton fck (MPa)", [20, 25, 30, 35, 40], index=1)
        fyk = st.selectbox("Acier fyk (MPa)", [400, 500], index=1)
        sigma = st.number_input("Contrainte admissible du sol (kPa)", 50.0, 800.0, d.sigma_sol, 10.0)
        st.subheader("Hypothèses")
        coef = st.slider("Coefficient de flambement l0/l", 0.5, 1.0, d.coef_flambement, 0.05)
        rho = st.slider("Taux d'acier max poteaux (%)", 1.0, 4.0, d.rho_max_poteau * 100, 0.5)

    projet = Projet(
        nom=nom, nb_etages=int(nb_etages), hauteur_etage=h_et, hauteur_rdc=h_rdc,
        portee_x=px, portee_y=py, nb_travees_x=int(nx), nb_travees_y=int(ny), usage=usage,
        g_revetement=g_rev, g_cloisons=g_cl, g_toiture=g_toit, q_toiture=q_toit,
        g_facade=g_fac, sigma_sol=sigma, coef_flambement=coef, rho_max_poteau=rho / 100,
        materiaux=Materiaux(fck=float(fck), fyk=float(fyk)),
    )
    try:
        res = dimensionner(projet)
    except ValueError as e:
        st.error(f"Calcul impossible : {e}")
        return

    dal, pou, fon, qua = res["dalle"], res["poutre"], res["fondations"], res["quantitatifs"]
    base_c = res["poteaux"]["centrale"][0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dalle", f"{dal['h']*100:.0f} cm")
    c2.metric("Poutre", f"{pou['b']*100:.0f} x {pou['h']*100:.0f} cm")
    c3.metric("Poteau central (base)", base_c["section_m"].replace("x", " x ") + " m")
    c4.metric("Béton total", f"{qua['beton_total_m3']:.0f} m³")

    anomalies = [f"Poteau {n} niveau {r['niveau']}" for n, niv in res["poteaux"].items()
                 for r in niv if r["statut"] != "OK"]
    if anomalies:
        st.warning("Éléments à revoir : " + ", ".join(anomalies))
    if pou["cisaillement"]["statut"] != "OK":
        st.warning("Poutre : effort tranchant non vérifié, augmenter la section.")
    if fon["taux_occupation"] >= 0.5:
        st.info(fon["recommandation"])

    t1, t2, t3, t4, t5, t6 = st.tabs(
        ["Dalles", "Poutres", "Poteaux", "Fondations", "Quantitatifs", "Export"])

    with t1:
        st.subheader("Plancher courant")
        a, b = st.columns(2)
        a.markdown(f"<div class='carte'><b>Épaisseur</b> : {dal['h']*100:.0f} cm &nbsp;|&nbsp; "
                   f"<b>Fonctionnement</b> : {dal['fonctionnement']}<br>"
                   f"G = {dal['g']:.2f} kPa, Q = {dal['q']:.2f} kPa, pu = {dal['pu']:.2f} kPa</div>",
                   unsafe_allow_html=True)
        b.write(f"M travée X = {dal['Mtx']:.2f} kN.m/m, M travée Y = {dal['Mty']:.2f} kN.m/m, "
                f"M appui = {dal['Ma']:.2f} kN.m/m")
        st.dataframe(pd.DataFrame([
            {"Zone": "Travée X", "As requis (cm²/m)": dal["travee_x"]["As_req_cm2_m"],
             "Armature": dal["travee_x"]["armature"]},
            {"Zone": "Travée Y", "As requis (cm²/m)": dal["travee_y"]["As_req_cm2_m"],
             "Armature": dal["travee_y"]["armature"]},
            {"Zone": "Appuis", "As requis (cm²/m)": dal["appui"]["As_req_cm2_m"],
             "Armature": dal["appui"]["armature"]},
        ]).round(2), hide_index=True, use_container_width=True)

    with t2:
        st.subheader(f"Poutre la plus longue (L = {pou['L']} m)")
        st.write(f"Section **{pou['b']*100:.0f} x {pou['h']*100:.0f} cm** - "
                 f"charge ELU = {pou['pu_kN_m']:.1f} kN/m")
        st.dataframe(pd.DataFrame([
            {"Zone": "Travée", "M (kN.m)": pou["Mt"], "As requis (cm²)": pou["travee"]["As_req_cm2"],
             "Armature": pou["travee"]["armature"]},
            {"Zone": "Appui", "M (kN.m)": pou["Ma"], "As requis (cm²)": pou["appui"]["As_req_cm2"],
             "Armature": pou["appui"]["armature"]},
        ]).round(2), hide_index=True, use_container_width=True)
        cs = pou["cisaillement"]
        st.write(f"Effort tranchant VEd = {pou['VEd']:.1f} kN -> "
                 + (f"cadres **{cs['cadres']}**" if cs["statut"] == "OK" else cs["statut"]))

    with t3:
        st.subheader("Poteaux par niveau")
        df_all = []
        for nom_p, niv in res["poteaux"].items():
            df = pd.DataFrame(niv)[["niveau", "section_m", "N_ed_kN", "elancement",
                                    "As_req_cm2", "armature", "taux_acier_%", "cadres", "statut"]]
            df.insert(0, "type", nom_p)
            df_all.append(df)
        full = pd.concat(df_all)
        choix = st.radio("Type de poteau", list(res["poteaux"]), horizontal=True)
        sel = full[full["type"] == choix].drop(columns="type").round(2)
        st.dataframe(style_statut(sel), hide_index=True, use_container_width=True)
        graph = pd.DataFrame({"Niveau": [r["niveau"] for r in res["poteaux"][choix]],
                              "Section (cm)": [r["c"] * 100 for r in res["poteaux"][choix]]})
        st.bar_chart(graph.set_index("Niveau"), color="#F59E0B")

    with t4:
        st.subheader("Semelles isolées")
        st.dataframe(pd.DataFrame([
            {"Type": n, "Nombre": fon[n]["nombre"], "N ser (kN)": fon[n]["N_ser_kN"],
             "B (m)": fon[n]["B_m"], "h (m)": fon[n]["h_m"],
             "σ réelle (kPa)": fon[n]["sigma_reelle_kPa"]}
            for n in ("centrale", "rive", "angle")]).round(2),
            hide_index=True, use_container_width=True)
        st.write(f"Taux d'occupation : **{fon['taux_occupation']*100:.0f} %** - {fon['recommandation']}")

    with t5:
        st.subheader("Quantitatifs estimés")
        k1, k2, k3 = st.columns(3)
        k1.metric("Béton", f"{qua['beton_total_m3']:.0f} m³")
        k2.metric("Acier", f"{qua['acier_total_kg(estime)']/1000:.1f} t")
        k3.metric("Ratio acier", f"{qua['ratio_acier_kg_m3']:.0f} kg/m³")
        st.bar_chart(pd.DataFrame({"m³": [qua["beton_dalles_m3"], qua["beton_poutres_m3"],
                                          qua["beton_poteaux_m3"]]},
                                  index=["Dalles", "Poutres", "Poteaux"]), color="#6366F1")
        st.caption("Estimation indicative (acier des poutres au ratio forfaitaire de 110 kg/m³).")

    with t6:
        st.subheader("Exporter")
        buf = io.StringIO()
        full.to_csv(buf, sep=";", index=False)
        st.download_button("⬇️ Poteaux (CSV)", buf.getvalue(), "poteaux.csv", "text/csv")
        st.download_button("⬇️ Résultats (JSON)", json.dumps(res, indent=2, ensure_ascii=False),
                           "resultats.json", "application/json")
        st.download_button("⬇️ Rapport (TXT)", rapport(res), "rapport.txt", "text/plain")
        with st.expander("Voir le rapport texte"):
            st.code(rapport(res))

    st.divider()
    st.caption("Non pris en compte : vent, séisme, contreventement, poinçonnement, flèches, "
               "fissuration, fondations réelles.")


if __name__ == "__main__":
    interface()