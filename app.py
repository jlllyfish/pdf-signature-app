import streamlit as st
import PyPDF2
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont
import io
import zipfile
from datetime import datetime
import os
import tempfile
import fitz  # PyMuPDF pour la prévisualisation
import numpy as np
import json
import base64

# Configuration de la page
st.set_page_config(
    page_title="Signature PDF - Traitement par Lots",
    page_icon="✍️",
    layout="wide"
)

st.title("✍️ Signature PDF - Traitement par Lots avec Prévisualisation")
st.markdown("---")

# Fonctions pour la gestion des profils
@st.cache_data
def get_profiles_file_path():
    """Retourne le chemin du fichier de profils"""
    # Utiliser le répertoire utilisateur pour la persistance
    home_dir = os.path.expanduser("~")
    app_dir = os.path.join(home_dir, ".streamlit_pdf_signature")
    os.makedirs(app_dir, exist_ok=True)
    return os.path.join(app_dir, "signature_profiles.json")

def load_profiles():
    """Charge les profils depuis le fichier JSON"""
    try:
        profiles_file = get_profiles_file_path()
        if os.path.exists(profiles_file):
            with open(profiles_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        st.error(f"Erreur lors du chargement des profils: {str(e)}")
    return {}

def save_profiles(profiles):
    """Sauvegarde les profils dans le fichier JSON"""
    try:
        profiles_file = get_profiles_file_path()
        with open(profiles_file, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde des profils: {str(e)}")
        return False

def delete_profile(profile_name, profiles):
    """Supprime un profil et sauvegarde"""
    if profile_name in profiles:
        # Supprimer aussi l'image de signature associée si elle existe
        if 'signature_image_path' in profiles[profile_name]:
            try:
                image_path = profiles[profile_name]['signature_image_path']
                if os.path.exists(image_path):
                    os.remove(image_path)
            except:
                pass
        
        del profiles[profile_name]
        save_profiles(profiles)
        return True
    return False

def save_signature_image(signature_file, profile_name):
    """Sauvegarde l'image de signature dans le dossier des profils"""
    try:
        profiles_dir = os.path.dirname(get_profiles_file_path())
        signature_filename = f"signature_{profile_name}.png"
        signature_path = os.path.join(profiles_dir, signature_filename)
        
        # Sauvegarder l'image
        signature_file.seek(0)
        image = Image.open(signature_file)
        image.save(signature_path, "PNG")
        
        return signature_path
    except Exception as e:
        st.error(f"Erreur lors de la sauvegarde de l'image: {str(e)}")
        return None

def load_signature_image(image_path):
    """Charge une image de signature depuis le chemin"""
    try:
        if os.path.exists(image_path):
            return Image.open(image_path)
    except:
        pass
    return None

def get_signature_as_uploadedfile(image_path):
    """Convertit une image sauvée en objet UploadedFile simulé"""
    try:
        if os.path.exists(image_path):
            with open(image_path, 'rb') as f:
                return io.BytesIO(f.read())
    except:
        pass
    return None

# Variables de session pour maintenir l'état
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []
if 'processing_complete' not in st.session_state:
    st.session_state.processing_complete = False
if 'current_profile' not in st.session_state:
    st.session_state.current_profile = None
if 'loaded_signature' not in st.session_state:
    st.session_state.loaded_signature = None

# Chargement des profils depuis le fichier
signature_profiles = load_profiles()

# Fonctions pour le traitement des pages
def parse_page_numbers(page_string, total_pages):
    """Parse une chaîne de pages personnalisées et retourne une liste de numéros de page"""
    if not page_string:
        return []
    
    pages = set()
    parts = page_string.replace(" ", "").split(",")
    
    for part in parts:
        if "-" in part:
            # Plage de pages (ex: 1-3)
            try:
                start, end = part.split("-")
                start = max(1, int(start))
                end = min(total_pages, int(end))
                pages.update(range(start, end + 1))
            except ValueError:
                continue
        else:
            # Page unique
            try:
                page_num = int(part)
                if 1 <= page_num <= total_pages:
                    pages.add(page_num)
            except ValueError:
                continue
    
    return sorted(list(pages))

def get_pages_to_sign(page_option, custom_pages, total_pages):
    """Détermine quelles pages doivent être signées selon l'option choisie"""
    if page_option == "Première page uniquement":
        return [1] if total_pages > 0 else []
    elif page_option == "Dernière page uniquement":
        return [total_pages] if total_pages > 0 else []
    elif page_option == "Toutes les pages":
        return list(range(1, total_pages + 1))
    elif page_option == "Pages personnalisées":
        return parse_page_numbers(custom_pages, total_pages)
    else:
        return [1]  # Par défaut, première page

# Sidebar pour les paramètres
with st.sidebar:
    st.header("⚙️ Paramètres de signature")
    
    # Gestion des profils de signature
    st.subheader("💾 Profils de signature")
    
    col_profile1, col_profile2 = st.columns([2, 1])
    
    with col_profile1:
        # Sélection d'un profil existant
        if signature_profiles:
            selected_profile = st.selectbox(
                "Charger un profil:",
                ["Nouveau profil"] + list(signature_profiles.keys()),
                key="profile_selector"
            )
        else:
            selected_profile = "Nouveau profil"
    
    with col_profile2:
        # Bouton pour supprimer un profil
        if selected_profile != "Nouveau profil" and signature_profiles:
            if st.button("🗑️", help="Supprimer ce profil", key="delete_profile"):
                if delete_profile(selected_profile, signature_profiles):
                    st.success(f"Profil '{selected_profile}' supprimé!")
                    signature_profiles = load_profiles()  # Recharger
                    st.rerun()
    
    # Chargement du profil sélectionné
    profile_loaded = False
    loaded_signature_path = None
    
    if selected_profile != "Nouveau profil" and selected_profile in signature_profiles:
        profile_data = signature_profiles[selected_profile]
        st.session_state.current_profile = selected_profile
        profile_loaded = True
        
        # Valeurs par défaut du profil
        default_x = profile_data.get('x_position', 400)
        default_y = profile_data.get('y_position', 100)
        default_width = profile_data.get('signature_width', 120)
        default_height = profile_data.get('signature_height', 60)
        default_text_offset = profile_data.get('text_offset_y', -20)
        default_text_size = profile_data.get('text_size', 8)
        default_page_option = profile_data.get('page_option', "Première page uniquement")
        default_custom_pages = profile_data.get('custom_pages', "")
        default_inclure_date = profile_data.get('inclure_date', True)
        default_nom_signataire = profile_data.get('nom_signataire', "")
        loaded_signature_path = profile_data.get('signature_image_path')
        
        st.success(f"✅ Profil '{selected_profile}' chargé")
        
        # Afficher l'image de signature du profil si elle existe
        if loaded_signature_path:
            loaded_image = load_signature_image(loaded_signature_path)
            if loaded_image:
                st.info("📷 Image de signature du profil chargée")
                st.image(loaded_image, caption=f"Signature du profil '{selected_profile}'", width=200)
                # Stocker l'image chargée dans la session
                st.session_state.loaded_signature = loaded_signature_path
            else:
                st.warning("⚠️ Image de signature du profil introuvable")
                st.session_state.loaded_signature = None
        else:
            st.session_state.loaded_signature = None
    else:
        # Valeurs par défaut pour nouveau profil
        default_x = 400
        default_y = 100
        default_width = 120
        default_height = 60
        default_text_offset = -20
        default_text_size = 8
        default_page_option = "Première page uniquement"
        default_custom_pages = ""
        default_inclure_date = True
        default_nom_signataire = ""
        st.session_state.current_profile = None
        st.session_state.loaded_signature = None
    
    st.markdown("---")
    
    # Upload de l'image de signature
    signature_file = st.file_uploader(
        "📝 Image de signature",
        type=['png', 'jpg', 'jpeg'],
        help="Uploadez votre image de signature (PNG, JPG, JPEG)"
    )
    
    # Gestion de l'image de signature (uploaded ou chargée depuis profil)
    active_signature = None
    
    if signature_file:
        # Image uploadée prioritaire
        sig_image = Image.open(signature_file)
        st.image(sig_image, caption="Aperçu de la signature uploadée", width=200)
        active_signature = signature_file
    elif st.session_state.loaded_signature:
        # Utiliser l'image du profil si pas d'upload
        loaded_image = load_signature_image(st.session_state.loaded_signature)
        if loaded_image:
            active_signature = get_signature_as_uploadedfile(st.session_state.loaded_signature)
            # L'image du profil est déjà affichée plus haut
    
    # Message d'information sur l'image active
    if active_signature:
        if signature_file:
            st.info("📷 Utilisation de l'image uploadée")
        else:
            st.info("📷 Utilisation de l'image du profil chargé")
    
    st.markdown("---")
    
    # Paramètres de position
    st.subheader("📍 Position de la signature")
    
    col1, col2 = st.columns(2)
    with col1:
        x_position = st.slider("Position X", 0, 500, default_x, help="Position horizontale en pixels")
        signature_width = st.slider("Largeur", 50, 200, default_width, help="Largeur de la signature en pixels")
    
    with col2:
        y_position = st.slider("Position Y", 0, 700, default_y, help="Position verticale en pixels")
        signature_height = st.slider("Hauteur", 30, 150, default_height, help="Hauteur de la signature en pixels")
    
    st.markdown("---")
    
    # Paramètres du texte
    st.subheader("📝 Informations textuelles")
    
    nom_signataire = st.text_input(
        "👤 Nom du signataire", 
        value=default_nom_signataire,
        placeholder="Nom Prénom"
    )
    
    inclure_date = st.checkbox("📅 Inclure la date", value=default_inclure_date)
    
    if inclure_date:
        date_signature = st.date_input(
            "Date de signature", 
            datetime.now().date(),
            format="DD/MM/YYYY",
            help="Format: jour/mois/année"
        )
    
    # Position du texte
    text_offset_y = st.slider("Décalage texte (Y)", -50, 50, default_text_offset, 
                             help="Décalage vertical du texte par rapport à la signature")
    
    # Taille du texte
    text_size = st.slider("Taille du texte", 6, 14, default_text_size, 
                         help="Taille de la police pour le nom et la date")
    
    st.markdown("---")
    
    # Sélection des pages
    st.subheader("📄 Pages à signer")
    
    page_option = st.selectbox(
        "Choisir les pages à signer:",
        ["Première page uniquement", "Dernière page uniquement", "Toutes les pages", "Pages personnalisées"],
        index=["Première page uniquement", "Dernière page uniquement", "Toutes les pages", "Pages personnalisées"].index(default_page_option),
        help="Sélectionnez quelles pages doivent être signées"
    )
    
    if page_option == "Pages personnalisées":
        custom_pages = st.text_input(
            "Pages à signer",
            value=default_custom_pages,
            placeholder="Ex: 1,3,5 ou 1-3 ou 1,3-5,7",
            help="Séparez par des virgules (1,3,5) ou utilisez des tirets pour les plages (1-3)"
        )
    else:
        custom_pages = ""  # Initialiser la variable même si non utilisée
    
    st.markdown("---")
    
    # Sauvegarde du profil
    st.subheader("💾 Sauvegarder le profil")
    
    col_save1, col_save2 = st.columns([2, 1])
    
    with col_save1:
        profile_name = st.text_input(
            "Nom du profil:",
            value=st.session_state.current_profile if st.session_state.current_profile else "",
            placeholder="Ex: Signature officielle",
            help="Donnez un nom à cette configuration"
        )
    
    with col_save2:
        if st.button("💾 Sauver", help="Sauvegarder ce profil", key="save_profile"):
            if profile_name.strip():
                # Sauvegarde de l'image de signature si présente
                signature_image_path = None
                if active_signature:
                    if signature_file:
                        # Sauvegarder la nouvelle image uploadée
                        signature_image_path = save_signature_image(signature_file, profile_name)
                    elif st.session_state.loaded_signature:
                        # Conserver l'image existante du profil
                        signature_image_path = st.session_state.loaded_signature
                
                # Création du profil
                profile_data = {
                    'x_position': x_position,
                    'y_position': y_position,
                    'signature_width': signature_width,
                    'signature_height': signature_height,
                    'text_offset_y': text_offset_y,
                    'text_size': text_size,
                    'page_option': page_option,
                    'custom_pages': custom_pages if page_option == "Pages personnalisées" else "",
                    'inclure_date': inclure_date,
                    'nom_signataire': nom_signataire,
                    'created_date': datetime.now().strftime("%d/%m/%Y %H:%M"),
                    'updated_date': datetime.now().strftime("%d/%m/%Y %H:%M")
                }
                
                # Ajouter le chemin de l'image si elle existe
                if signature_image_path:
                    profile_data['signature_image_path'] = signature_image_path
                
                signature_profiles[profile_name] = profile_data
                st.session_state.current_profile = profile_name
                
                # Sauvegarde persistante
                if save_profiles(signature_profiles):
                    if signature_image_path:
                        st.success(f"✅ Profil '{profile_name}' sauvegardé avec image de signature!")
                    else:
                        st.success(f"✅ Profil '{profile_name}' sauvegardé!")
                    st.rerun()
                else:
                    st.error("❌ Erreur lors de la sauvegarde")
            else:
                st.error("❌ Veuillez saisir un nom pour le profil")
    
    # Liste des profils existants
    if signature_profiles:
        with st.expander(f"📋 Profils sauvegardés ({len(signature_profiles)})", expanded=False):
            for profile_name, profile_data in signature_profiles.items():
                st.write(f"**{profile_name}**")
                st.write(f"- Position: {profile_data['x_position']},{profile_data['y_position']}")
                st.write(f"- Taille: {profile_data['signature_width']}x{profile_data['signature_height']}")
                st.write(f"- Pages: {profile_data['page_option']}")
                if 'nom_signataire' in profile_data and profile_data['nom_signataire']:
                    st.write(f"- Signataire: {profile_data['nom_signataire']}")
                if 'signature_image_path' in profile_data:
                    st.write("- 📷 Image de signature: ✅")
                else:
                    st.write("- 📷 Image de signature: ❌")
                st.write(f"- Créé: {profile_data['created_date']}")
                if 'updated_date' in profile_data:
                    st.write(f"- Modifié: {profile_data['updated_date']}")
                st.write("---")
    
    # Bouton pour nettoyer tous les profils (en cas de besoin)
    if signature_profiles:
        if st.button("🧹 Nettoyer tous les profils", help="Supprimer tous les profils sauvegardés", key="clear_all_profiles"):
            if st.button("⚠️ Confirmer la suppression", key="confirm_clear"):
                try:
                    profiles_file = get_profiles_file_path()
                    if os.path.exists(profiles_file):
                        os.remove(profiles_file)
                    st.success("✅ Tous les profils ont été supprimés!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erreur: {str(e)}")

# Zone principale avec onglets
tab1, tab2 = st.tabs(["📁 Upload & Prévisualisation", "🚀 Traitement"])

with tab1:
    col_main1, col_main2 = st.columns([1, 1])
    
    with col_main1:
        st.header("📁 Upload des fichiers PDF")
        
        # Upload multiple de PDFs
        pdf_files = st.file_uploader(
            "Sélectionnez les fichiers PDF à signer",
            type=['pdf'],
            accept_multiple_files=True,
            help="Vous pouvez sélectionner plusieurs fichiers PDF",
            key="pdf_uploader"
        )
        
        if pdf_files:
            st.success(f"✅ {len(pdf_files)} fichier(s) PDF uploadé(s)")
            
            # Sélection du PDF à prévisualiser
            if len(pdf_files) > 1:
                selected_pdf_index = st.selectbox(
                    "📖 Choisir le PDF à prévisualiser:",
                    range(len(pdf_files)),
                    format_func=lambda x: pdf_files[x].name
                )
            else:
                selected_pdf_index = 0
    
    with col_main2:
        st.header("🔍 Prévisualisation PDF")
        
        # Message d'aide si pas de signature ou nom
        if not active_signature:
            st.info("📝 Uploadez une image de signature ou chargez un profil avec image pour voir la prévisualisation")
        elif not nom_signataire:
            st.info("👤 Saisissez un nom de signataire pour voir la prévisualisation complète")
        elif pdf_files and active_signature:
            try:
                # Sélection du PDF à prévisualiser
                selected_pdf = pdf_files[selected_pdf_index]
                
                # Lecture du PDF sans modifier la position du pointeur
                pdf_bytes = selected_pdf.getvalue()
                
                # Utilisation de PyMuPDF pour convertir en image
                pdf_document = fitz.open(stream=pdf_bytes)
                
                # Déterminer quelle page prévisualiser selon l'option choisie
                total_pages = len(pdf_document)
                
                if page_option == "Première page uniquement":
                    preview_page_num = 0
                    preview_info = "Page 1"
                elif page_option == "Dernière page uniquement":
                    preview_page_num = total_pages - 1
                    preview_info = f"Page {total_pages} (dernière)"
                elif page_option == "Toutes les pages":
                    preview_page_num = 0  # Montrer la première page comme exemple
                    preview_info = "Page 1 (signature sur toutes les pages)"
                elif page_option == "Pages personnalisées" and custom_pages:
                    # Essayer de montrer la première page spécifiée
                    pages_to_sign = parse_page_numbers(custom_pages, total_pages)
                    if pages_to_sign:
                        preview_page_num = pages_to_sign[0] - 1  # Convertir en 0-indexé
                        if len(pages_to_sign) == 1:
                            preview_info = f"Page {pages_to_sign[0]}"
                        else:
                            preview_info = f"Page {pages_to_sign[0]} (première des pages sélectionnées: {', '.join(map(str, pages_to_sign))})"
                    else:
                        preview_page_num = 0
                        preview_info = "Page 1 (aucune page valide spécifiée)"
                else:
                    preview_page_num = 0
                    preview_info = "Page 1"
                
                # S'assurer que le numéro de page est valide
                if preview_page_num >= total_pages:
                    preview_page_num = 0
                    preview_info = "Page 1 (page demandée non trouvée)"
                
                # Obtenir la page à prévisualiser
                preview_page = pdf_document[preview_page_num]
                
                # Conversion en image avec une résolution plus élevée
                mat = fitz.Matrix(1.5, 1.5)  # Zoom x1.5 pour éviter les images trop lourdes
                pix = preview_page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                
                # Chargement de l'image avec PIL
                pdf_image = Image.open(io.BytesIO(img_data))
                
                # Conversion des coordonnées PDF vers coordonnées image
                pdf_width, pdf_height = preview_page.rect.width, preview_page.rect.height
                img_width, img_height = pdf_image.size
                
                # Facteurs de conversion
                scale_x = img_width / pdf_width
                scale_y = img_height / pdf_height
                
                # Conversion des coordonnées (PDF: origine en bas à gauche, Image: origine en haut à gauche)
                img_x = int(x_position * scale_x)
                img_y = int(img_height - (y_position + signature_height) * scale_y)
                img_sig_width = int(signature_width * scale_x)
                img_sig_height = int(signature_height * scale_y)
                
                # Création d'une copie pour dessiner la prévisualisation
                preview_image = pdf_image.copy()
                draw = ImageDraw.Draw(preview_image)
                
                # Dessin du rectangle de signature avec fond semi-transparent
                # Création d'une overlay pour la transparence
                overlay = Image.new('RGBA', preview_image.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                
                # Rectangle de fond pour la signature
                overlay_draw.rectangle([img_x, img_y, img_x + img_sig_width, img_y + img_sig_height], 
                                     fill=(255, 0, 0, 50), outline=(255, 0, 0, 255), width=3)
                
                # Fusionner l'overlay avec l'image principale
                preview_image = preview_image.convert('RGBA')
                preview_image = Image.alpha_composite(preview_image, overlay)
                preview_image = preview_image.convert('RGB')
                
                # Redessiner le contour
                draw = ImageDraw.Draw(preview_image)
                draw.rectangle([img_x, img_y, img_x + img_sig_width, img_y + img_sig_height], 
                             outline="red", width=3)
                
                # Ajout du texte de prévisualisation
                try:
                    # Calcul de la taille de police adaptée
                    font_size = max(10, int(img_sig_height / 5))
                    font = ImageFont.load_default()
                except:
                    font = ImageFont.load_default()
                
                if nom_signataire:
                    text_y = img_y + img_sig_height + int(abs(text_offset_y) * scale_y)
                    # Formatage du texte avec "Signé par"
                    signature_text = f"Signé par: {nom_signataire}"
                    draw.text((img_x, text_y), signature_text, fill="red", font=font)
                    
                    if inclure_date:
                        date_y = text_y + 15
                        # Format de date DD/MM/YYYY
                        date_formatted = date_signature.strftime("%d/%m/%Y")
                        draw.text((img_x, date_y), f"Date: {date_formatted}", fill="red", font=font)
                
                # Affichage de l'image avec prévisualisation
                st.image(preview_image, caption=f"Prévisualisation: {selected_pdf.name} - {preview_info}", use_container_width=True)
                
                # Informations détaillées sur la page et position
                col_info_a, col_info_b = st.columns(2)
                with col_info_a:
                    st.info(f"📍 Position signature: X={x_position}px, Y={y_position}px")
                with col_info_b:
                    st.info(f"📄 Prévisualisation: {preview_info}")
                
                # Information sur les pages qui seront réellement signées
                if page_option == "Pages personnalisées" and custom_pages:
                    pages_to_sign = parse_page_numbers(custom_pages, total_pages)
                    if pages_to_sign:
                        if len(pages_to_sign) > 1:
                            st.success(f"✅ Signature sera apposée sur les pages: {', '.join(map(str, pages_to_sign))}")
                        else:
                            st.success(f"✅ Signature sera apposée sur la page: {pages_to_sign[0]}")
                    else:
                        st.warning("⚠️ Aucune page valide spécifiée")
                elif page_option == "Toutes les pages":
                    st.success(f"✅ Signature sera apposée sur toutes les pages (1 à {total_pages})")
                elif page_option == "Dernière page uniquement":
                    st.success(f"✅ Signature sera apposée sur la dernière page ({total_pages})")
                else:
                    st.success("✅ Signature sera apposée sur la première page")
                
                # Aperçu des informations de signature
                with st.expander("ℹ️ Informations de signature", expanded=False):
                    col_info1, col_info2 = st.columns(2)
                    with col_info1:
                        st.write(f"**📝 Texte:** Signé par: {nom_signataire}")
                        if inclure_date:
                            date_formatted = date_signature.strftime("%d/%m/%Y")
                            st.write(f"**📅 Date:** {date_formatted}")
                        st.write(f"**📄 Document:** {total_pages} page(s)")
                    with col_info2:
                        st.write(f"**📏 Taille texte:** {text_size}px")
                        st.write(f"**📐 Décalage:** {text_offset_y}px")
                        st.write(f"**📄 Pages:** {page_option}")
                        if page_option == "Pages personnalisées" and custom_pages:
                            st.write(f"**📋 Pages spécifiques:** {custom_pages}")
                        if st.session_state.current_profile:
                            st.write(f"**💾 Profil:** {st.session_state.current_profile}")
                
                pdf_document.close()
                
            except Exception as e:
                st.error(f"Erreur lors de la prévisualisation: {str(e)}")
                st.info("💡 Astuce: Assurez-vous que le PDF n'est pas protégé et réessayez.")
        
        # Affichage du profil chargé même sans PDF
        if profile_loaded and not pdf_files:
            st.info(f"💾 Profil '{selected_profile}' chargé. Uploadez un PDF pour voir la prévisualisation.")

with tab2:
    st.header("🚀 Traitement des PDFs")
    
    # Récapitulatif des paramètres
    if active_signature and nom_signataire and pdf_files:
        with st.expander("📋 Récapitulatif des paramètres", expanded=True):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.write("**📝 Signature:**")
                if signature_file:
                    st.write(f"- Fichier: {signature_file.name}")
                else:
                    st.write(f"- Fichier: Image du profil")
                st.write(f"- Nom: Signé par: {nom_signataire}")
                if inclure_date:
                    date_formatted = date_signature.strftime("%d/%m/%Y")
                    st.write(f"- Date: {date_formatted}")
                st.write(f"- Taille texte: {text_size}px")
                if st.session_state.current_profile:
                    st.write(f"- Profil utilisé: {st.session_state.current_profile}")
            
            with col2:
                st.write("**📍 Position:**")
                st.write(f"- X: {x_position}px")
                st.write(f"- Y: {y_position}px")
                st.write(f"- Taille: {signature_width}x{signature_height}px")
            
            with col3:
                st.write("**📁 Fichiers:**")
                st.write(f"- Nombre: {len(pdf_files)}")
                st.write(f"- Pages à signer: {page_option}")
                if page_option == "Pages personnalisées" and custom_pages:
                    st.write(f"- Pages spécifiques: {custom_pages}")
                st.write("- Noms:")
                for pdf in pdf_files[:3]:  # Afficher les 3 premiers
                    st.write(f"  • {pdf.name}")
                if len(pdf_files) > 3:
                    st.write(f"  • ... et {len(pdf_files) - 3} autres")

def create_signature_overlay(signature_img, nom, date_sig, x, y, width, height, text_offset, font_size):
    """Crée un PDF overlay avec la signature et les informations"""
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)
    
    try:
        # Ajout de l'image de signature
        if signature_img:
            # Réinitialiser le pointeur de l'image
            signature_img.seek(0)
            # Créer un objet ImageReader pour ReportLab
            img_reader = ImageReader(signature_img)
            c.drawImage(img_reader, x, y, width=width, height=height, mask='auto')
        
        # Ajout du nom avec "Signé par"
        if nom:
            c.setFont("Helvetica", font_size)
            signature_text = f"Signé par: {nom}"
            c.drawString(x, y + text_offset, signature_text)
        
        # Ajout de la date au format DD/MM/YYYY
        if date_sig:
            c.setFont("Helvetica", max(6, font_size - 1))  # Taille légèrement plus petite pour la date
            date_formatted = date_sig.strftime("%d/%m/%Y")
            c.drawString(x, y + text_offset - 12, f"Date: {date_formatted}")
        
        c.save()
        packet.seek(0)
        return packet
        
    except Exception as e:
        st.error(f"Erreur lors de la création de l'overlay: {str(e)}")
        return None

def process_pdf(pdf_file, signature_overlay_packet, page_option, custom_pages=""):
    """Traite un seul PDF en ajoutant la signature sur les pages spécifiées"""
    try:
        # Obtenir les bytes du PDF sans modifier le pointeur
        pdf_bytes = pdf_file.getvalue()
        
        # Lecture du PDF original
        pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
        pdf_writer = PdfWriter()
        
        # Nombre total de pages
        total_pages = len(pdf_reader.pages)
        
        # Déterminer les pages à signer
        pages_to_sign = get_pages_to_sign(page_option, custom_pages, total_pages)
        
        # Lecture de l'overlay de signature
        if signature_overlay_packet is None:
            return None
            
        signature_overlay_packet.seek(0)
        overlay_pdf = PdfReader(signature_overlay_packet)
        signature_page = overlay_pdf.pages[0]
        
        # Traitement de chaque page
        for page_num in range(total_pages):
            page = pdf_reader.pages[page_num]
            
            # Ajout de la signature sur les pages sélectionnées (conversion 0-indexé)
            if (page_num + 1) in pages_to_sign:
                page.merge_page(signature_page)
            
            pdf_writer.add_page(page)
        
        # Création du PDF résultant
        output_buffer = io.BytesIO()
        pdf_writer.write(output_buffer)
        
        return output_buffer.getvalue()
    
    except Exception as e:
        st.error(f"Erreur lors du traitement de {pdf_file.name}: {str(e)}")
        return None

# Bouton de traitement
st.markdown("---")

# Affichage des résultats de traitement s'ils existent
if st.session_state.processing_complete and st.session_state.processed_files:
    st.success(f"✅ {len(st.session_state.processed_files)} fichier(s) traité(s) avec succès!")
    
    # Boutons de téléchargement
    if len(st.session_state.processed_files) > 1:
        # Création du fichier ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_info in st.session_state.processed_files:
                zip_file.writestr(file_info['name'], file_info['data'])
        
        zip_buffer.seek(0)
        
        st.download_button(
            label="📥 Télécharger tous les PDFs signés (ZIP)",
            data=zip_buffer.getvalue(),
            file_name=f"pdfs_signes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mime="application/zip",
            key="download_zip"
        )
    
    elif len(st.session_state.processed_files) == 1:
        st.download_button(
            label="📥 Télécharger le PDF signé",
            data=st.session_state.processed_files[0]['data'],
            file_name=st.session_state.processed_files[0]['name'],
            mime="application/pdf",
            key="download_single"
        )
    
    # Bouton pour nouveau traitement
    if st.button("🔄 Nouveau traitement", key="reset"):
        st.session_state.processed_files = []
        st.session_state.processing_complete = False
        st.rerun()

# Bouton de traitement principal
if not st.session_state.processing_complete:
    if st.button("🚀 Traiter les PDFs", type="primary", use_container_width=True):
        if not active_signature:
            st.error("❌ Veuillez uploader une image de signature ou charger un profil avec image")
        elif not nom_signataire:
            st.error("❌ Veuillez saisir le nom du signataire")
        elif not pdf_files:
            st.error("❌ Veuillez uploader au moins un fichier PDF")
        elif page_option == "Pages personnalisées" and not custom_pages.strip():
            st.error("❌ Veuillez spécifier les pages à signer (ex: 1,3,5 ou 1-3)")
        else:
            # Traitement des PDFs
            with st.spinner("🔄 Traitement en cours..."):
                # Création de l'overlay de signature
                signature_overlay = create_signature_overlay(
                    active_signature,
                    nom_signataire,
                    date_signature if inclure_date else None,
                    x_position,
                    y_position,
                    signature_width,
                    signature_height,
                    text_offset_y,
                    text_size
                )
                
                if signature_overlay is None:
                    st.error("❌ Erreur lors de la création de la signature")
                else:
                    processed_files = []
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    # Traitement de chaque PDF
                    for i, pdf_file in enumerate(pdf_files):
                        status_text.text(f"Traitement de {pdf_file.name}...")
                        
                        # Reset du pointeur pour l'overlay
                        signature_overlay.seek(0)
                        
                        # Traitement du PDF avec les options de pages
                        processed_pdf = process_pdf(
                            pdf_file, 
                            signature_overlay, 
                            page_option, 
                            custom_pages if page_option == "Pages personnalisées" else ""
                        )
                        
                        if processed_pdf:
                            processed_files.append({
                                'name': f"signed_{pdf_file.name}",
                                'data': processed_pdf
                            })
                        
                        # Mise à jour de la barre de progression
                        progress_bar.progress((i + 1) / len(pdf_files))
                    
                    # Stockage des résultats dans la session
                    st.session_state.processed_files = processed_files
                    st.session_state.processing_complete = True
                    
                    status_text.empty()
                    progress_bar.empty()
                    
                    # Recharger la page pour afficher les résultats
                    st.rerun()

# Section d'aide
with st.expander("❓ Aide et conseils"):
    st.markdown("""
    ### 📋 Instructions d'utilisation:
    
    1. **Profils**: Créez et sauvegardez vos configurations de signature
    2. **Image de signature**: Uploadez une image PNG, JPG ou JPEG de votre signature
    3. **Position**: Ajustez la position X/Y et la taille de la signature
    4. **Pages**: Choisissez quelles pages signer (première, dernière, toutes, ou personnalisées)
    5. **Prévisualisation**: Visualisez exactement où sera placée la signature
    6. **Informations**: Saisissez votre nom et choisissez d'inclure la date
    7. **PDFs**: Sélectionnez un ou plusieurs fichiers PDF à signer
    8. **Traitement**: Cliquez sur "Traiter les PDFs" pour générer les fichiers signés
    
    ### 💡 Conseils:
    
    - Utilisez l'onglet "Upload & Prévisualisation" pour voir exactement où sera placée la signature
    - Testez différentes positions avec les sliders en temps réel
    - Utilisez une image de signature avec un fond transparent (PNG) pour un meilleur rendu
    - La signature sera apposée sur la première page de chaque PDF
    - Les coordonnées (0,0) correspondent au coin inférieur gauche de la page PDF
    
    ### 🔧 Paramètres recommandés:
    
    - **Position X**: 350-450 (côté droit)
    - **Position Y**: 50-150 (bas de page)
    - **Taille**: 100-150 pixels de largeur
    
    ### 💾 Gestion des profils:
    
    - **Créer un profil**: Configurez vos paramètres puis donnez un nom et cliquez "Sauver"
    - **Charger un profil**: Sélectionnez un profil existant dans la liste déroulante
    - **Modifier un profil**: Chargez-le, modifiez les paramètres, et sauvez avec le même nom
    - **Supprimer un profil**: Utilisez le bouton 🗑️ à côté du sélecteur
    - **Sauvegarde d'images**: Les images de signature sont automatiquement sauvées avec les profils
    - **Sauvegarde persistante**: Les profils sont sauvés dans `~/.streamlit_pdf_signature/`
    - **Exemples de profils**:
      - "Signature officielle": Position bas droite, première page + image
      - "Paraphe toutes pages": Petit format, toutes les pages + image
      - "Validation contrat": Pages 1 et dernière page + image
    
    ### 📄 Options de pages:
    
    - **Première page uniquement**: Signature sur la page 1 seulement
    - **Dernière page uniquement**: Signature sur la dernière page
    - **Toutes les pages**: Signature sur chaque page du document
    - **Pages personnalisées**: Spécifiez exactement quelles pages signer
      - Pages individuelles: `1,3,5`
      - Plages de pages: `1-3` (pages 1, 2, 3)
      - Combinaison: `1,3-5,7` (pages 1, 3, 4, 5, 7)
    
    ### 🎯 Fonctionnalités de prévisualisation:
    
    - **Aperçu en temps réel**: Voyez la position exacte sur votre PDF
    - **Rectangle rouge**: Indique l'emplacement de la signature
    - **Texte rouge**: Position du nom et de la date
    - **Sélection de PDF**: Choisissez quel PDF prévisualiser si vous en avez plusieurs
    - **Expander d'infos**: Détails sur la signature dans la prévisualisation
    
    ### 🔧 Résolution des problèmes:
    
    - Si la signature n'apparaît pas, vérifiez que l'image a un fond transparent
    - Si le traitement s'arrête, rechargez la page et réessayez
    - Les PDFs protégés par mot de passe ne peuvent pas être traités
    - **Profils**: Sauvés dans `~/.streamlit_pdf_signature/signature_profiles.json`
    - **Nettoyage**: Utilisez le bouton "Nettoyer tous les profils" si nécessaire
    """)

# Footer
st.markdown("---")
st.markdown("🔒 Tous les fichiers sont traités localement et ne sont pas stockés sur le serveur.")
st.markdown("Made with ❤️ by Jellyfish - 2025")
