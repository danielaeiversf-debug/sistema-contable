import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

# Configuración visual de Streamlit (Diseño corporativo del Sector Sociedades)
st.set_page_config(page_title="ONVIO Automatizador - Sector Sociedades", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    h1 { color: #1e3a8a; font-family: 'Segoe UI', sans-serif; font-weight: 700; }
    h3 { color: #475569; font-family: 'Segoe UI', sans-serif; }
    .stButton>button { background-color: #1e3a8a; color: white; border-radius: 6px; font-weight: 600; }
    .stButton>button:hover { background-color: #2563eb; color: white; }
    </style>
    """, unsafe_allow_html=True)

# 1. MÓDULO DE SEGURIDAD INTERNA PARA LAS 6 PERSONAS
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

if not st.session_state["autenticado"]:
    st.title("🔐 Acceso Restringido - Estudio Contable")
    clave_ingresada = st.text_input("Introduzca la clave de acceso del sector:", type="password")
    if st.button("Ingresar al Sistema"):
        if clave_ingresada == "sociedades2026":
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("❌ Clave incorrecta. Solicítela al administrador del sector.")
    st.stop()

# --- A PARTIR DE AQUÍ EL SISTEMA SE DESBLOQUEA ---

st.title("🤖 Sistema de Automatización Contable")
st.subheader("Sector Sociedades - Motor de Importación Directa para 'ONVIO'")

# 2. DEFINICIÓN DE BASES DE DATOS INTERNAS (REGLAS POR EMPRESA/BANCO)
CUENTA_PUENTE_DEF = "13000000"

# Reglas fijas para Asociación Civil (Banco Comafi)
CUENTA_BANCO_COMAFI = "11016010"
EQUIVALENCIAS_COMAFI = {
    "MANTENIMIENTO DE": ("53010000", "GASTOS BANCARIOS"),
    "COMISION EMISION": ("53010000", "GASTOS BANCARIOS"),
    "COMISION TRANSFERENCIAS": ("53010000", "GASTOS BANCARIOS"),
    "COMISION": ("53010000", "GASTOS BANCARIOS"),
    "PAGO ELECTRONICO": ("21012010", "PROVEEDORES"),
    "PAGO DE SERVICIOS": ("21012010", "PROVEEDORES"),
    "PAGO DE CHEQUE": ("21012010", "PROVEEDORES"),
    "EBANKIN": ("21012010", "PROVEEDORES"),
    "PROV": ("21012010", "PROVEEDORES"),
    "RECIBIDA": ("11031010", "DEUDORES POR SERVICIOS"),
    "RECIBID": ("11031010", "DEUDORES POR SERVICIOS"),
    "DATAN": ("11031010", "DEUDORES POR SERVICIOS"),
    "OURENSE": ("11031010", "DEUDORES POR SERVICIOS"),
    "CASSINERIO": ("11031010", "DEUDORES POR SERVICIOS"),
    "DEPOSITO": ("11011000", "CAJA"),
    "DEBITOS - TASA": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEBITOS ART 45": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEB LEY 25413": ("53070000", "IMPUESTO DEB LEY 25413"),
    "IMPUESTO A LOS DEBITOS": ("53070000", "IMPUESTO DEB LEY 25413"),
    "CREDITOS-TASA G": ("53080000", "IMPUESTO CRED LEY 25413"),
    "CRED LEY 25413": ("53080000", "IMPUESTO CRED LEY 25413"),
    "IMPUESTO A LOS CREDITOS": ("53080000", "IMPUESTO CRED LEY 25413"),
    "IVA - ALICUOTA": ("11032050", "DGI IVA RET. Y PERCEPCIONES"),
    "SUELDOS": ("21013010", "SUELDOS Y JORNALES A PAGAR"),
    "HONORARIOS": ("52020000", "HONORARIOS PROFESIONALES"),
}

# Reglas fijas para Alambrados Cambren S.R.L. (Banco Galicia)
CUENTA_BANCO_GALICIA = "11016040"
EQUIVALENCIAS_GALICIA = {
    "PRISMA-COMERCIOS": ("21012010", "PROVEEDORES"),
    "VISA EST.": ("21012010", "PROVEEDORES"),
    "MAST EST.": ("21012010", "PROVEEDORES"),
    "AMEX EST.": ("21012010", "PROVEEDORES"),
    "PRESTAMO BCO GALICIA": ("21011010", "PRESTAMO BCO GALICIA 808028444671"),
    "CUOTA DE PRESTAMO": ("21011010", "PRESTAMO BCO GALICIA 808028444671"),
    "IMP. DEB. LEY 25413": ("11032310", "IMP. LEY 25413 S/DEBITOS Y CREDITOS"),
    "IMP. CRE. LEY 25413": ("11032310", "IMP. LEY 25413 S/DEBITOS Y CREDITOS"),
    "COMISION SERVICE": ("53010000", "BANCARIOS"),
    "COMISION CHEQUE": ("53010000", "BANCARIOS"),
    "COM. DEPOSITO": ("53010000", "BANCARIOS"),
    "IVA": ("11032040", "DGI IVA CREDITO FISCAL 21%"),
    "PERCEP. IVA": ("11032050", "DGI IVA RET. Y PERCEPCIONES"),
    "TRANSFERENCIA DE TERCEROS": ("11031010", "DEUDORES POR VENTAS"),
    "TRANSFERENCIAS CASH PROVEEDORES": ("21012010", "PROVEEDORES"),
    "TRF INMED PROVEED": ("21012010", "PROVEEDORES"),
    "PAGO VISA EMPRESA": ("21012010", "PROVEEDORES"),
    "DEB. AUTOM. DE SERV.": ("21012010", "PROVEEDORES"),
    "TRANSFERENCIAS CASH AFIP": ("21014030", "DGI IVA A PAGAR"),
}

# Barra lateral parametrizada
st.sidebar.header("⚙️ Selección de Entorno de Trabajo")
empresa_seleccionada = st.sidebar.selectbox("Seleccionar Empresa Cliente", ["Asociación Civil 12 Casas", "Alambrados Cambren S.R.L."])
nro_asiento_inicial = st.sidebar.number_input("Número de Asiento Inicial", min_value=1, value=1, step=1)
cuenta_puente = st.sidebar.text_input("Cuenta Puente", value=CUENTA_PUENTE_DEF)

# Configurar variables automáticamente según la empresa elegida
if empresa_seleccionada == "Alambrados Cambren S.R.L.":
    banco_activo = "Banco Galicia"
    cuenta_banco_activa = CUENTA_BANCO_GALICIA
    equivalencias_activas = EQUIVALENCIAS_GALICIA
else:
    banco_activo = "Banco Comafi"
    cuenta_banco_activa = CUENTA_BANCO_COMAFI
    equivalencias_activas = EQUIVALENCIAS_COMAFI

st.sidebar.info(f"🏦 Banco detectado: {banco_activo}\n💳 Cuenta contable activa: {cuenta_banco_activa}")

if st.sidebar.button("🔒 Cerrar Sesión"):
    st.session_state["autenticado"] = False
    st.rerun()

st.markdown(f"### 1. Cargar Extractos de: **{empresa_seleccionada}** ({banco_activo})")
archivos_cargados = st.file_uploader("Arrastrá uno o más PDFs del extracto bancario a la vez", type=["pdf"], accept_multiple_files=True)

# --- MOTOR DE LECTURA COMAFI ---
def procesar_lineas_comafi(text):
    movimientos = []
    lineas = text.split("\n")
    fecha_en_memoria = None
    concepto_acumulado = ""
    freno_activado = False
    
    for linea in lineas:
        linea_upper = linea.upper()
        partes = linea.split()
        if len(partes) == 0:
            continue
        if str(partes[0]).upper() == "TRANSPORTE":
            continue
        if any(keyword in linea_upper for keyword in ["GARANTIA DE HASTA", "LEY 24.485", "DECRETO 540/95", "CIRCULAR OPASI"]):
            continue 
        if "SALDO AL:" in linea_upper or "IMPUESTOS DEBITADOS" in linea_upper or "BASE IMPONIBLE" in linea_upper:
            freno_activado = True
        if freno_activado:
            continue 
            
        primer_item = str(partes[0])
        tiene_fecha = re.match(r'^\d{2}/\d{2}/\d{2}$', primer_item)
        
        if tiene_fecha:
            fecha_en_memoria = primer_item
            if "Saldo Anterior" in linea:
                continue
            concepto_acumulado = " ".join([x for x in partes[1:] if not re.match(r'^\d{6,12}$', x) and "," not in x])
        else:
            if not fecha_en_memoria:
                continue
            texto_secundario = " ".join([x for x in partes if not re.match(r'^\d{6,12}$', x) and "," not in x])
            if texto_secundario:
                concepto_acumulado += " " + texto_secundario

        importes_validos = []
        for token in partes:
            if re.match(r'^\d{6,12}$', token): 
                continue
            token_clean = token.replace(".", "").replace(",", ".")
            if token_clean.endswith("-"):
                token_clean = "-" + token_clean[:-1]
            try:
                if "," in token: 
                    importes_validos.append(float(token_clean))
            except ValueError:
                continue

        if not importes_validos:
            continue  
            
        importe_real = importes_validos[-2] if len(importes_validos) >= 2 else importes_validos[-1]
        desc_final = concepto_acumulado.strip()
        
        es_credito = False
        desc_upper = desc_final.upper()
        if "IMPUESTO A LOS CREDITOS" in desc_upper or "CREDITOS-TASA G" in desc_upper or "CRED LEY 25413" in desc_upper:
            es_credito = False
        elif any(kw in desc_upper for kw in ["RECIBIDA", "CREDITOS", "DEPOSITO", "ACREDITADO", "RECIBID", "TONELLI", "CPS", "OURENSE", "CASSINERIO"]):
            es_credito = True
            
        movimientos.append({"Fecha": str(fecha_en_memoria), "Descripción": desc_final, "Importe": abs(importe_real), "EsCredito": es_credito})
        concepto_acumulado = ""
    return movimientos

# --- NUEVO: MOTOR DE LECTURA GALICIA ---
def procesar_lineas_galicia(text):
    movimientos = []
    lineas = text.split("\n")
    freno_activado = False
    
    for linea in lineas:
        linea_upper = linea.upper()
        if "CONSOLIDADO DE RETENCIÓN" in linea_upper or "TOTALES MENSUALES" in linea_upper or "GARANTIA DE HASTA" in linea_upper:
            freno_activado = True
        if freno_activado:
            continue
            
        partes = linea.split()
        if len(partes) < 3:
            continue
            
        # Comprobar si arranca con fecha válida (DD/MM/YY)
        if not re.match(r'^\d{2}/\d{2}/\d{2}$', str(partes[0])):
            continue
            
        fecha = str(partes[0])
        
        # Buscar importes contables en el renglón de Galicia
        valores = []
        for p in partes[1:]:
            p_clean = p.replace(".", "").replace(",", ".")
            if p_clean.startswith("-"):
                try:
                    valores.append(float(p_clean))
                except: pass
            else:
                try:
                    if "," in p:
                        valores.append(float(p_clean))
                except: pass
                
        if len(valores) < 2:
            continue 
            
        importe_banco = valores[-2]
        str_importe = partes[-2]
        str_saldo = partes[-1]
        
        # Aislar descripción removiendo la fecha, el importe y el saldo final de la línea
        tokens_desc = [x for x in partes[1:] if x != str_importe and x != str_saldo and not re.match(r'^\d{6,12}$', x)]
