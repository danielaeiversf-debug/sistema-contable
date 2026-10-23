import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

# Configuración visual de Streamlit (Ligada al sector y más corporativa)
st.set_page_config(page_title="ONVIO Automatizador - Sector Sociedades", layout="wide")

# Cambiar diseño visual y tipografía mediante estilos CSS inyectados
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
st.subheader("Asociaciones Civiles - Motor de Importación Directa para 'ONVIO'")

# CUENTAS CONTABLES FIJAS
CUENTA_BANCO_COMAFI = "11016010"  # CTA/CTE $ COMAFI 1070-01085-6
CUENTA_PUENTE_DEF = "13000000"

EQUIVALENCIAS_BASE = {
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

# Barra lateral parametrizada y con selectores avanzados para la empresa
st.sidebar.header("⚙️ Configuración del Trabajo")
banco_seleccionado = st.sidebar.selectbox("Seleccionar Banco", ["Banco Comafi", "Banco Santander (Próximamente)", "MercadoPago (Próximamente)"])
plan_seleccionado = st.sidebar.selectbox("Plan de Cuentas Empresa", ["Asociación Civil 12 Casas", "S.R.L. Genérico", "S.A. Genérico"])
nro_asiento_inicial = st.sidebar.number_input("Número de Asiento Inicial", min_value=1, value=1, step=1)
cuenta_puente = st.sidebar.text_input("Cuenta Puente", value=CUENTA_PUENTE_DEF)

if st.sidebar.button("🔒 Cerrar Sesión"):
    st.session_state["autenticado"] = False
    st.rerun()

st.markdown("### 1. Cargar Extractos Bancarios")
archivos_cargados = st.file_uploader("Arrastrá uno o más PDFs del extracto bancario a la vez", type=["pdf"], accept_multiple_files=True)

# Inicializar variables globales de memoria en el estado de sesión si no existen
if "fecha_global" not in st.session_state:
    st.session_state["fecha_global"] = None
if "concepto_global" not in st.session_state:
    st.session_state["concepto_global"] = ""

def procesar_lineas_comafi(text):
    movimientos = []
    lineas = text.split("\n")
    freno_activado = False
    
    for linea in lineas:
        linea_upper = linea.upper()
        
        if any(keyword in linea_upper for keyword in ["TRANSPORTE", "GARANTIA DE HASTA", "LEY 24.485", "DECRETO 540/95", "CIRCULAR OPASI"]):
            continue 
            
        if "SALDO AL:" in linea_upper or "IMPUESTOS DEBITADOS" in linea_upper or "BASE IMPONIBLE" in linea_upper:
            freno_activado = True
            
        if freno_activado:
            continue 
            
        partes = linea.split()
        if len(partes) == 0:
            continue
            
        primer_item = partes[0]
        tiene_fecha = re.match(r'^\d{2}/\d{2}/\d{2}$', primer_item)
        
        if tiene_fecha:
            st.session_state["fecha_global"] = str(primer_item)
            if "Saldo Anterior" in linea:
                continue
            st.session_state["concepto_global"] = " ".join([x for x in partes[1:] if not re.match(r'^\d{6,12}$', x) and "," not in x])
        else:
            if not st.session_state["fecha_global"]:
                continue
            texto_secundario = " ".join([x for x in partes if not re.match(r'^\d{6,12}$', x) and "," not in x])
            if texto_secundario:
                st.session_state["concepto_global"] += " " + texto_secundario

        importes_validos = []
        for token in partes:
            if re.match(r'^\d{6,12}$', token): 
                continue
            token_clean = token.replace(".", "").replace(",", ".")
            if token_clean.endswith("-"):
                token_clean = "-" + token_clean[:-1]
            try:
                if "," in token: 
                    val = float(token_clean)
                    importes_validos.append(val)
            except ValueError:
                continue

        if not importes_validos:
            continue  
            
        if len(importes_validos) >= 2:
            importe_real = importes_validos[-2]
        else:
            importe_real = importes_validos[-1]
            
        desc_final = st.session_state["concepto_global"].strip()
        
        es_credito = False
        desc_upper = desc_final.upper()
        if any(kw in desc_upper for kw in ["RECIBIDA", "CREDITOS", "DEPOSITO", "ACREDITADO", "RECIBID", "TONELLI", "CPS", "OURENSE", "TRANSPORTES"]):
            es_credito = True
            
        movimientos.append({
            "Fecha": str(st.session_state["fecha_global"]),
            "Descripción": desc_final,
            "Importe": abs(importe_real),
            "EsCredito": es_credito
        })
        st.session_state["concepto_global"] = ""
        
    return movimientos

if archivos_cargados:
    movimientos_totales = []
    st.session_state["fecha_global"] = None
    st.session_state["concepto_global"] = ""
    
    for archivo in archivos_cargados:
        with pdfplumber.open(archivo) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    movimientos_totales.extend(procesar_lineas_comafi(text))
                
    if movimientos_totales:
        df_origen = pd.DataFrame(movimientos_totales)
        st.success(f"🔥 ¡Éxito! Se procesaron {len(archivos_cargados)} archivos sueltos y se extrajeron {len(df_origen)} transacciones reales.")
        
        filas_planilla = []
        asiento_actual = int(nro_asiento_inicial)
        fechas_unicas = df_origen["Fecha"].unique()
        
        for fecha in fechas_unicas:
            df_dia = df_origen[df_origen["Fecha"] == str(fecha)]
            pase_actual = 1
            
            for idx, fila in df_dia.iterrows():
                desc = fila["Descripción"]
                importe = fila["Importe"]
                es_credito = fila["EsCredito"]
                
                desc_upper = desc.upper()
                codigo_cuenta = str(cuenta_puente)
                nombre_cuenta = "CUENTA PUENTE"
                
                for clave, datos in EQUIVALENCIAS_BASE.items():
                    if clave in desc_upper:
                        codigo_cuenta = str(datos[0])
                        nombre_cuenta = str(datos[1])
                        break
                
                if es_credito:
                    monto_imputacion = -importe
                    monto_banco = float(importe)
                else:
                    monto_imputacion = float(importe)
                    monto_banco = -importe
                
                filas_planilla.append([asiento_actual, pase_actual, str(fecha), "Asiento Resumen Bancario", codigo_cuenta, float(monto_imputacion), 0.0, f"{nombre_cuenta} - {desc}", "", "", "", ""])
                pase_actual += 1
                
                filas_planilla.append([asiento_actual, pase_actual, str(fecha), "Asiento Resumen Bancario", str(CUENTA_BANCO_COMAFI), float(monto_banco), 0.0, f"COMAFI CTA CTE - {desc}", "", "", "", ""])
                pase_actual += 1
                
            asiento_actual += 1
            
        columnas_onvio = ["Número de asiento", "Número de Pase", "Fecha", "Concepto", "Código de cuenta", "Importe en moneda local", "Importe en moneda ext.present.", "Leyenda", "Código de centro de costos", "Porcentaje de distribución", "Imp.mon.local dist.C.Costos", "Imp.mon.present.dist.C.Costos"]
        df_resultado = pd.DataFrame(filas_planilla, columns=columnas_onvio)
        
        if not df_resultado.empty:
            st.markdown("### 2. Previsualización y Control")
            st.dataframe(df_resultado)
            
            st.markdown("### 3. Exportación Final")
            output = io.BytesIO()
