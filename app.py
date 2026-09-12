import streamlit as st
import pandas as pd
import os
import hashlib
import secrets
import string
from datetime import date

st.set_page_config(page_title="SitePulse", page_icon="🏗️", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    h1 { font-weight: 800; letter-spacing: -0.5px; }
    div[data-testid="stMetric"] {
        background-color: #1B2A3D; border: 1px solid #2A3B52;
        border-radius: 12px; padding: 15px 10px;
    }
    div[data-testid="stMetricLabel"] { color: #A9B4C0; }
    .stButton > button {
        border-radius: 8px; font-weight: 600; border: none; transition: all 0.2s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px); box-shadow: 0 4px 10px rgba(232, 163, 61, 0.3);
    }
    section[data-testid="stSidebar"] { border-right: 1px solid #2A3B52; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# FICHIERS DE DONNÉES
# =========================================================
FICHIERS = {
    "users": "data/users.csv",
    "chantiers": "data/chantiers.csv",
    "taches": "data/taches.csv",
    "stock": "data/stock.csv",
    "avancement": "data/avancement.csv",
    "messages": "data/messages.csv",
}

COLONNES = {
    "users": ["identifiant", "nom", "mot_de_passe_hash", "role", "chantier_id", "doit_changer_mdp"],
    "chantiers": ["chantier_id", "nom_chantier", "ingenieur_identifiant", "date_creation"],
    "taches": ["id", "chantier_id", "description", "zone", "assigne", "statut", "date_maj", "assigne_par"],
    "stock": ["date", "chantier_id", "materiau", "quantite", "unite", "mouvement", "responsable"],
    "avancement": ["date", "chantier_id", "zone", "pourcentage", "commentaire"],
    "messages": ["id", "chantier_id", "expediteur_identifiant", "expediteur_nom", "expediteur_role", "destinataire_identifiant", "contenu", "date"],
}

def init_fichiers():
    os.makedirs("data", exist_ok=True)
    for cle, chemin in FICHIERS.items():
        if not os.path.exists(chemin):
            pd.DataFrame(columns=COLONNES[cle]).to_csv(chemin, index=False)
        else:
            df = pd.read_csv(chemin, dtype=str)
            colonnes_manquantes = [c for c in COLONNES[cle] if c not in df.columns]
            if colonnes_manquantes:
                for c in colonnes_manquantes:
                    df[c] = ""
                df.to_csv(chemin, index=False)

def charger(cle):
    df = pd.read_csv(FICHIERS[cle], dtype=str)
    return df.fillna("")

def sauvegarder(cle, df):
    df.to_csv(FICHIERS[cle], index=False)

init_fichiers()

# =========================================================
# OUTILS SÉCURITÉ
# =========================================================
def hash_mdp(mdp):
    return hashlib.sha256(mdp.encode()).hexdigest()

def generer_mdp_aleatoire(longueur=8):
    caracteres = string.ascii_letters + string.digits
    return ''.join(secrets.choice(caracteres) for _ in range(longueur))

def creer_utilisateur(identifiant, nom, role, chantier_id, mdp, doit_changer):
    df = charger("users")
    nouvelle_ligne = pd.DataFrame([{
        "identifiant": identifiant, "nom": nom, "mot_de_passe_hash": hash_mdp(mdp),
        "role": role, "chantier_id": chantier_id, "doit_changer_mdp": "1" if doit_changer else "0"
    }])
    df = pd.concat([df, nouvelle_ligne], ignore_index=True)
    sauvegarder("users", df)

def authentifier(identifiant, mdp):
    df = charger("users")
    ligne = df[df["identifiant"] == identifiant]
    if ligne.empty:
        return None
    if ligne.iloc[0]["mot_de_passe_hash"] == hash_mdp(mdp):
        return ligne.iloc[0].to_dict()
    return None

def changer_mdp(identifiant, nouveau_mdp):
    df = charger("users")
    df.loc[df["identifiant"] == identifiant, "mot_de_passe_hash"] = hash_mdp(nouveau_mdp)
    df.loc[df["identifiant"] == identifiant, "doit_changer_mdp"] = "0"
    sauvegarder("users", df)

def envoyer_message(chantier_id, expediteur, contenu, destinataire_identifiant=""):
    df = charger("messages")
    nouvel_id = "1" if df.empty else str(int(df["id"].astype(int).max()) + 1)
    nouvelle_ligne = pd.DataFrame([{
        "id": nouvel_id, "chantier_id": chantier_id,
        "expediteur_identifiant": expediteur["identifiant"], "expediteur_nom": expediteur["nom"],
        "expediteur_role": expediteur["role"], "destinataire_identifiant": destinataire_identifiant,
        "contenu": contenu, "date": str(date.today())
    }])
    df = pd.concat([df, nouvelle_ligne], ignore_index=True)
    sauvegarder("messages", df)

def calculer_stock_actuel(df_stock):
    """Retourne un DataFrame : matériau, unité, quantité disponible."""
    if df_stock.empty:
        return pd.DataFrame(columns=["materiau", "unite", "quantite_disponible"])
    df = df_stock.copy()
    df["quantite"] = pd.to_numeric(df["quantite"], errors="coerce").fillna(0)
    df["quantite_signee"] = df.apply(lambda r: r["quantite"] if r["mouvement"] == "Entrée" else -r["quantite"], axis=1)
    stock = df.groupby(["materiau", "unite"], as_index=False)["quantite_signee"].sum()
    stock = stock.rename(columns={"quantite_signee": "quantite_disponible"})
    return stock.sort_values("materiau")

def afficher_stock(df_stock, chantier_id=None, utilisateur=None, modifiable=False):
    stock_actuel = calculer_stock_actuel(df_stock)
    if stock_actuel.empty:
        st.info("Aucun matériau en stock pour l'instant.")
        return
    for _, ligne in stock_actuel.iterrows():
        emoji = "🟢" if ligne["quantite_disponible"] >= 0 else "🔴"
        if modifiable:
            col1, col2, col3 = st.columns([3, 1.3, 1])
            with col1:
                st.write(f"{emoji} **{ligne['materiau']}** — {ligne['quantite_disponible']:.0f} {ligne['unite']}")
            with col2:
                cle_qte = f"use_{ligne['materiau']}_{ligne['unite']}"
                qte_utilisee = st.number_input("Quantité utilisée", min_value=0.0, step=1.0, key=cle_qte, label_visibility="collapsed")
            with col3:
                if st.button("J'ai utilisé", key=f"btn_{cle_qte}"):
                    if qte_utilisee > 0:
                        df = charger("stock")
                        nouvelle_ligne = pd.DataFrame([{
                            "date": date.today(), "chantier_id": chantier_id, "materiau": ligne["materiau"],
                            "quantite": qte_utilisee, "unite": ligne["unite"], "mouvement": "Sortie",
                            "responsable": utilisateur["nom"]
                        }])
                        df = pd.concat([df, nouvelle_ligne], ignore_index=True)
                        sauvegarder("stock", df)
                        st.success(f"{qte_utilisee:.0f} {ligne['unite']} de {ligne['materiau']} déduit du stock.")
                        st.rerun()
                    else:
                        st.error("Indique une quantité supérieure à 0.")
        else:
            st.write(f"{emoji} **{ligne['materiau']}** — {ligne['quantite_disponible']:.0f} {ligne['unite']}")

# =========================================================
# ÉTAT DE SESSION
# =========================================================
if "user" not in st.session_state:
    st.session_state.user = None
if "chantier_actif" not in st.session_state:
    st.session_state.chantier_actif = None

# =========================================================
# ÉCRAN : ACCUEIL — connexion ou création de compte Ingénieur
# =========================================================
if st.session_state.user is None:
    col_g, col_c, col_d = st.columns([1, 1.2, 1])
    with col_c:
        st.markdown("<div style='text-align:center; font-size:52px;'>🏗️</div>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align:center;'>SitePulse</h1>"
                     "<p style='text-align:center; color:#A9B4C0;'>The heartbeat of your construction site.</p>",
                     unsafe_allow_html=True)

        onglet_connexion, onglet_inscription = st.tabs(["Se connecter", "Créer un compte Ingénieur"])

        with onglet_connexion:
            with st.container(border=True):
                identifiant = st.text_input("Identifiant", key="login_id")
                mdp = st.text_input("Mot de passe", type="password", key="login_mdp")
                if st.button("Se connecter", use_container_width=True):
                    utilisateur = authentifier(identifiant, mdp)
                    if utilisateur is None:
                        st.error("Identifiant ou mot de passe incorrect.")
                    else:
                        st.session_state.user = utilisateur
                        st.rerun()

        with onglet_inscription:
            with st.container(border=True):
                st.caption("Seul un Ingénieur peut créer son propre compte. Les Chefs de chantier et Ouvriers sont ajoutés depuis l'onglet Équipe une fois connecté.")
                nom = st.text_input("Nom complet", key="signup_nom")
                nouvel_id = st.text_input("Identifiant de connexion", key="signup_id")
                mdp1 = st.text_input("Mot de passe", type="password", key="signup_mdp1")
                mdp2 = st.text_input("Confirmer le mot de passe", type="password", key="signup_mdp2")
                if st.button("Créer mon compte", use_container_width=True):
                    df_check = charger("users")
                    if not nom or not nouvel_id or not mdp1:
                        st.error("Merci de remplir tous les champs.")
                    elif mdp1 != mdp2:
                        st.error("Les mots de passe ne correspondent pas.")
                    elif nouvel_id in df_check["identifiant"].values:
                        st.error("Cet identifiant existe déjà, choisis-en un autre.")
                    else:
                        creer_utilisateur(nouvel_id, nom, "Ingénieur", "", mdp1, doit_changer=False)
                        st.success("Compte créé ! Connecte-toi dans l'onglet 'Se connecter'.")
    st.stop()

user = st.session_state.user

# =========================================================
# ÉCRAN : CHANGEMENT DE MOT DE PASSE OBLIGATOIRE
# =========================================================
if str(user["doit_changer_mdp"]) == "1":
    col_g, col_c, col_d = st.columns([1, 1.2, 1])
    with col_c:
        st.markdown("<h2 style='text-align:center;'>🔒 Sécurise ton compte</h2>", unsafe_allow_html=True)
        st.caption("C'est ta première connexion : choisis un nouveau mot de passe personnel.")
        with st.container(border=True):
            nouveau1 = st.text_input("Nouveau mot de passe", type="password")
            nouveau2 = st.text_input("Confirmer le nouveau mot de passe", type="password")
            if st.button("Valider", use_container_width=True):
                if len(nouveau1) < 4:
                    st.error("Le mot de passe doit faire au moins 4 caractères.")
                elif nouveau1 != nouveau2:
                    st.error("Les mots de passe ne correspondent pas.")
                else:
                    changer_mdp(user["identifiant"], nouveau1)
                    user["doit_changer_mdp"] = "0"
                    st.session_state.user = user
                    st.success("Mot de passe mis à jour !")
                    st.rerun()
    st.stop()

# =========================================================
# EN-TÊTE COMMUN
# =========================================================
col_titre, col_deco = st.columns([5, 1])
with col_titre:
    st.title(f"🏗️ SitePulse — {user['role']}")
with col_deco:
    if st.button("Se déconnecter"):
        st.session_state.user = None
        st.session_state.chantier_actif = None
        st.rerun()
st.caption(f"Connecté : {user['nom']} ({user['identifiant']})")

# =========================================================
# 👷 INGÉNIEUR — accès complet, PLUSIEURS chantiers possibles
# =========================================================
if user["role"] == "Ingénieur":
    df_chantiers = charger("chantiers")
    mes_chantiers = df_chantiers[df_chantiers["ingenieur_identifiant"] == user["identifiant"]]

    # Sélecteur de chantier actif (si au moins un existe)
    if not mes_chantiers.empty:
        if st.session_state.chantier_actif not in mes_chantiers["chantier_id"].values:
            st.session_state.chantier_actif = mes_chantiers.iloc[0]["chantier_id"]

        options = list(mes_chantiers["chantier_id"])
        labels = list(mes_chantiers["nom_chantier"] + " (" + mes_chantiers["chantier_id"] + ")")
        index_actif = options.index(st.session_state.chantier_actif)

        choix_label = st.selectbox("🏗️ Chantier actif", labels, index=index_actif, key="select_chantier_actif")
        st.session_state.chantier_actif = options[labels.index(choix_label)]

    chantier_id = st.session_state.chantier_actif

    onglets = st.tabs(["🏗️ Mes chantiers", "👥 Équipe", "📋 Assigner une tâche", "📊 Analyse & KPIs", "📨 Messagerie"])

    # --- Créer / lister les chantiers ---
    with onglets[0]:
        st.subheader("Créer un nouveau chantier")
        nom_chantier = st.text_input("Nom du chantier", key="nom_nouveau_chantier")
        if st.button("Créer ce chantier"):
            if not nom_chantier.strip():
                st.error("Donne un nom au chantier.")
            else:
                nouveau_id = "CH" + secrets.token_hex(3)
                nouvelle_ligne = pd.DataFrame([{
                    "chantier_id": nouveau_id, "nom_chantier": nom_chantier,
                    "ingenieur_identifiant": user["identifiant"], "date_creation": str(date.today())
                }])
                df_chantiers = pd.concat([df_chantiers, nouvelle_ligne], ignore_index=True)
                sauvegarder("chantiers", df_chantiers)
                st.session_state.chantier_actif = nouveau_id
                st.success(f"Chantier '{nom_chantier}' créé !")
                st.rerun()

        st.divider()
        st.subheader("Mes chantiers")
        if mes_chantiers.empty:
            st.info("Aucun chantier pour l'instant — crée le premier ci-dessus.")
        else:
            for _, ligne in mes_chantiers.iterrows():
                marque = "⭐ " if ligne["chantier_id"] == chantier_id else ""
                st.write(f"{marque}**{ligne['nom_chantier']}** — créé le {ligne['date_creation']} ({ligne['chantier_id']})")

    # --- Gestion de l'équipe (du chantier actif) ---
    with onglets[1]:
        if not chantier_id:
            st.warning("Crée d'abord un chantier dans l'onglet précédent.")
        else:
            st.subheader("Ajouter un membre")
            col1, col2 = st.columns(2)
            with col1:
                nouveau_nom = st.text_input("Nom complet", key="nom_membre")
                nouvel_id_login = st.text_input("Identifiant de connexion", key="id_membre")
            with col2:
                nouveau_role = st.selectbox("Rôle", ["Chef de chantier", "Ouvrier"])

            if st.button("Ajouter ce membre"):
                df_check = charger("users")
                if nouvel_id_login in df_check["identifiant"].values:
                    st.error("Cet identifiant existe déjà, choisis-en un autre.")
                else:
                    mdp_genere = generer_mdp_aleatoire()
                    creer_utilisateur(nouvel_id_login, nouveau_nom, nouveau_role, chantier_id, mdp_genere, doit_changer=True)
                    st.success(f"Compte créé pour {nouveau_nom} !")
                    st.code(f"Identifiant : {nouvel_id_login}\nMot de passe temporaire : {mdp_genere}", language="text")
                    st.caption("⚠️ Transmets ces identifiants à la personne — ce mot de passe ne sera plus affiché.")

            st.divider()
            st.subheader("Équipe de ce chantier")
            df_equipe = charger("users")
            df_equipe = df_equipe[(df_equipe["chantier_id"] == chantier_id) & (df_equipe["role"] != "Ingénieur")]
            st.dataframe(df_equipe[["identifiant", "nom", "role"]], use_container_width=True)

    # --- Assigner une tâche (du chantier actif) ---
    with onglets[2]:
        if not chantier_id:
            st.warning("Crée d'abord un chantier.")
        else:
            df_ouvriers = charger("users")
            df_ouvriers = df_ouvriers[(df_ouvriers["chantier_id"] == chantier_id) & (df_ouvriers["role"] == "Ouvrier")]

            if df_ouvriers.empty:
                st.info("Ajoute d'abord des ouvriers dans l'onglet Équipe.")
            else:
                description = st.text_input("Description de la tâche")
                zone = st.text_input("Zone")
                ouvrier_choisi = st.selectbox("Assigner à", df_ouvriers["identifiant"] + " — " + df_ouvriers["nom"])
                identifiant_ouvrier = ouvrier_choisi.split(" — ")[0]

                if st.button("Créer et assigner la tâche"):
                    df_taches = charger("taches")
                    nouvel_id = "1" if df_taches.empty else str(int(df_taches["id"].astype(int).max()) + 1)
                    nouvelle_ligne = pd.DataFrame([{
                        "id": nouvel_id, "chantier_id": chantier_id, "description": description,
                        "zone": zone, "assigne": identifiant_ouvrier, "statut": "À faire",
                        "date_maj": str(date.today()), "assigne_par": user["identifiant"]
                    }])
                    df_taches = pd.concat([df_taches, nouvelle_ligne], ignore_index=True)
                    sauvegarder("taches", df_taches)
                    st.success("Tâche assignée !")

            st.divider()
            st.subheader("Toutes les tâches de ce chantier")
            df_taches = charger("taches")
            st.dataframe(df_taches[df_taches["chantier_id"] == chantier_id], use_container_width=True)

    # --- Analyse & KPIs (du chantier actif) ---
    with onglets[3]:
        if not chantier_id:
            st.warning("Crée d'abord un chantier.")
        else:
            with st.expander("➕ Ajouter une mise à jour d'avancement"):
                col1, col2 = st.columns(2)
                with col1:
                    zone_ing = st.text_input("Zone / lot", key="zone_ing")
                    pourcentage_ing = st.slider("Pourcentage d'avancement", 0, 100, 0, key="pct_ing")
                with col2:
                    commentaire_ing = st.text_area("Commentaire", key="comment_ing")
                if st.button("Enregistrer", key="save_avancement_ing"):
                    df = charger("avancement")
                    nouvelle_ligne = pd.DataFrame([{
                        "date": date.today(), "chantier_id": chantier_id, "zone": zone_ing,
                        "pourcentage": pourcentage_ing, "commentaire": commentaire_ing
                    }])
                    df = pd.concat([df, nouvelle_ligne], ignore_index=True)
                    sauvegarder("avancement", df)
                    st.success("Avancement enregistré.")
                    st.rerun()

            df_taches = charger("taches")
            df_taches = df_taches[df_taches["chantier_id"] == chantier_id]
            df_stock = charger("stock")
            df_stock = df_stock[df_stock["chantier_id"] == chantier_id]
            df_avancement = charger("avancement")
            df_avancement = df_avancement[df_avancement["chantier_id"] == chantier_id]

            col1, col2 = st.columns(2)
            with col1:
                total = len(df_taches)
                termine = len(df_taches[df_taches["statut"] == "Terminé"]) if not df_taches.empty else 0
                st.metric("Tâches terminées", f"{termine}/{total}")
            with col2:
                moy = pd.to_numeric(df_avancement["pourcentage"], errors="coerce").mean() if not df_avancement.empty else 0
                st.metric("Avancement moyen", f"{moy:.1f} %" if pd.notna(moy) else "0 %")

            st.divider()
            st.subheader("📦 État du stock")
            st.caption("Indique une quantité et clique sur \"J'ai utilisé\" pour la déduire du stock.")
            afficher_stock(df_stock, chantier_id=chantier_id, utilisateur=user, modifiable=True)

            st.divider()
            if not df_avancement.empty:
                df_avancement["pourcentage"] = pd.to_numeric(df_avancement["pourcentage"], errors="coerce")
                dernieres = df_avancement.sort_values("date").groupby("zone").last()
                st.subheader("Avancement par zone")
                st.bar_chart(dernieres["pourcentage"])

                st.subheader("Mes commentaires d'avancement")
                for _, ligne in df_avancement.sort_values("date", ascending=False).iterrows():
                    if ligne["commentaire"]:
                        with st.container(border=True):
                            st.caption(f"{ligne['zone']} — {ligne['date']}")
                            st.write(ligne["commentaire"])

            st.subheader("Détail des tâches")
            st.dataframe(df_taches, use_container_width=True)

    # --- Messagerie (du chantier actif) ---
    with onglets[4]:
        if not chantier_id:
            st.warning("Crée d'abord un chantier.")
        else:
            df_equipe = charger("users")
            df_equipe = df_equipe[(df_equipe["chantier_id"] == chantier_id) & (df_equipe["role"] != "Ingénieur")]

            if df_equipe.empty:
                st.info("Ajoute d'abord des membres à ton équipe.")
            else:
                membre_choisi = st.selectbox("Conversation avec", df_equipe["identifiant"] + " — " + df_equipe["nom"], key="select_conv")
                identifiant_membre = membre_choisi.split(" — ")[0]

                df_messages = charger("messages")
                conversation = df_messages[
                    (df_messages["chantier_id"] == chantier_id) &
                    ((df_messages["expediteur_identifiant"] == identifiant_membre) |
                     (df_messages["destinataire_identifiant"] == identifiant_membre))
                ].sort_values("date")

                if conversation.empty:
                    st.info("Aucun message avec cette personne pour l'instant.")
                else:
                    for _, m in conversation.iterrows():
                        with st.container(border=True):
                            if m["expediteur_identifiant"] == user["identifiant"]:
                                st.markdown(f"**Moi (Ingénieur)** — {m['date']}")
                            else:
                                st.markdown(f"**{m['expediteur_nom']}** — {m['date']}")
                            st.write(m["contenu"])

                reponse = st.text_area("Répondre", key="reponse_ing")
                if st.button("Envoyer la réponse", key="envoi_reponse_ing"):
                    if reponse.strip():
                        envoyer_message(chantier_id, user, reponse, destinataire_identifiant=identifiant_membre)
                        st.success("Réponse envoyée !")
                        st.rerun()
                    else:
                        st.error("Le message ne peut pas être vide.")

# =========================================================
# 👨‍💼 CHEF DE CHANTIER
# =========================================================
elif user["role"] == "Chef de chantier":
    chantier_id = user.get("chantier_id", "")
    onglet = st.tabs(["📦 Stock", "📈 Avancement (lecture)", "📨 Messagerie"])

    with onglet[0]:
        st.subheader("Ajouter un mouvement")
        col1, col2 = st.columns(2)
        with col1:
            materiau = st.text_input("Matériau")
            quantite = st.number_input("Quantité", min_value=0.0, step=1.0)
            unite = st.text_input("Unité (sacs, m³, tonnes...)")
        with col2:
            mouvement = st.radio("Type de mouvement", ["Entrée", "Sortie"])

        if st.button("Enregistrer le mouvement"):
            df = charger("stock")
            nouvelle_ligne = pd.DataFrame([{
                "date": date.today(), "chantier_id": chantier_id, "materiau": materiau,
                "quantite": quantite, "unite": unite, "mouvement": mouvement, "responsable": user["nom"]
            }])
            df = pd.concat([df, nouvelle_ligne], ignore_index=True)
            sauvegarder("stock", df)
            st.success("Mouvement enregistré.")
            st.rerun()

        st.divider()
        df_stock = charger("stock")
        df_stock_chantier = df_stock[df_stock["chantier_id"] == chantier_id]

        st.subheader("📦 État actuel du stock")
        afficher_stock(df_stock_chantier)

        st.divider()
        st.subheader("Historique des mouvements")
        st.dataframe(df_stock_chantier, use_container_width=True)

    # --- Avancement : consultation uniquement, saisi par l'ingénieur ---
    with onglet[1]:
        st.caption("L'avancement est saisi par l'ingénieur — tu peux le consulter ici.")
        df_avancement = charger("avancement")
        df_avancement = df_avancement[df_avancement["chantier_id"] == chantier_id]

        if df_avancement.empty:
            st.info("Aucune donnée d'avancement pour l'instant.")
        else:
            df_avancement["pourcentage"] = pd.to_numeric(df_avancement["pourcentage"], errors="coerce")
            dernieres = df_avancement.sort_values("date").groupby("zone").last()
            st.subheader("Avancement par zone")
            st.bar_chart(dernieres["pourcentage"])

            st.subheader("Commentaires de l'ingénieur")
            for _, ligne in df_avancement.sort_values("date", ascending=False).iterrows():
                if ligne["commentaire"]:
                    with st.container(border=True):
                        st.caption(f"{ligne['zone']} — {ligne['date']}")
                        st.write(ligne["commentaire"])

    # --- Messagerie : conversation avec l'ingénieur ---
    with onglet[2]:
        st.subheader("Messagerie avec l'ingénieur")
        df_messages = charger("messages")
        conversation = df_messages[
            (df_messages["chantier_id"] == chantier_id) &
            ((df_messages["expediteur_identifiant"] == user["identifiant"]) |
             (df_messages["destinataire_identifiant"] == user["identifiant"]))
        ].sort_values("date")

        if conversation.empty:
            st.info("Aucun message pour l'instant.")
        else:
            for _, m in conversation.iterrows():
                with st.container(border=True):
                    if m["expediteur_identifiant"] == user["identifiant"]:
                        st.markdown(f"**Moi** — {m['date']}")
                    else:
                        st.markdown(f"**{m['expediteur_nom']} (Ingénieur)** — {m['date']}")
                    st.write(m["contenu"])

        message = st.text_area("Nouveau message", key="msg_chef")
        if st.button("Envoyer", key="envoi_chef"):
            if message.strip():
                envoyer_message(chantier_id, user, message)
                st.success("Message envoyé !")
                st.rerun()
            else:
                st.error("Le message ne peut pas être vide.")

# =========================================================
# 👨‍🔧 OUVRIER
# =========================================================
elif user["role"] == "Ouvrier":
    chantier_id = user.get("chantier_id", "")
    onglet = st.tabs(["✅ Mes tâches", "📨 Messagerie"])

    with onglet[0]:
        df = charger("taches")
        df_mes_taches = df[(df["assigne"] == user["identifiant"]) & (df["statut"] != "Terminé")]

        if df_mes_taches.empty:
            st.info("Aucune tâche en attente. 👍")
        else:
            for _, ligne in df_mes_taches.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.markdown(f"**{ligne['description']}**")
                        st.caption(f"Zone : {ligne['zone']} — Statut : {ligne['statut']}")
                    with c2:
                        if st.button("✅ Terminé", key=f"tache_{ligne['id']}"):
                            df.loc[df["id"] == ligne["id"], "statut"] = "Terminé"
                            df.loc[df["id"] == ligne["id"], "date_maj"] = str(date.today())
                            sauvegarder("taches", df)
                            st.rerun()

    with onglet[1]:
        st.subheader("Messagerie avec l'ingénieur")
        df_messages = charger("messages")
        conversation = df_messages[
            (df_messages["chantier_id"] == chantier_id) &
            ((df_messages["expediteur_identifiant"] == user["identifiant"]) |
             (df_messages["destinataire_identifiant"] == user["identifiant"]))
        ].sort_values("date")

        if conversation.empty:
            st.info("Aucun message pour l'instant.")
        else:
            for _, m in conversation.iterrows():
                with st.container(border=True):
                    if m["expediteur_identifiant"] == user["identifiant"]:
                        st.markdown(f"**Moi** — {m['date']}")
                    else:
                        st.markdown(f"**{m['expediteur_nom']} (Ingénieur)** — {m['date']}")
                    st.write(m["contenu"])

        message = st.text_area("Nouveau message", key="msg_ouvrier")
        if st.button("Envoyer", key="envoi_ouvrier"):
            if message.strip():
                envoyer_message(chantier_id, user, message)
                st.success("Message envoyé !")
                st.rerun()
            else:
                st.error("Le message ne peut pas être vide.")
