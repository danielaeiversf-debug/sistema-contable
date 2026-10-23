import streamlit as st
import pandas as pd
import pdfplumber
import io
import re
import unicodedata

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

# Las claves se comparan SIN acentos, puntos ni guiones ("Débitos" = "DEBITOS", "Caj.Aut." = "CAJ AUT").
# Se recorre en orden y gana la PRIMERA clave que aparece en la descripción.

# a) Solo para movimientos que el banco informa en la columna CRÉDITOS (ingresos)
EQUIVALENCIAS_CREDITO = {
    "DEPOSITO": ("11011000", "CAJA"),
    "CAJ AUT": ("11011000", "CAJA"),
    "RECIB": ("11031010", "DEUDORES POR SERVICIOS"),
    "CVU": ("11031010", "DEUDORES POR SERVICIOS"),
    "TERCEROS": ("11031010", "DEUDORES POR SERVICIOS"),
    "TRANSF": ("11031010", "DEUDORES POR SERVICIOS"),
    "DATAN": ("11031010", "DEUDORES POR SERVICIOS"),
    "OURENSE": ("11031010", "DEUDORES POR SERVICIOS"),
}

# b) Para todos los movimientos (débitos, y créditos que no entraron en la lista anterior)
EQUIVALENCIAS_BASE = {
    "IMPUESTO A LOS CRED": ("53080000", "IMPUESTO CRED LEY 25413"),
    "CREDITOS TASA": ("53080000", "IMPUESTO CRED LEY 25413"),
    "CRED LEY 25413": ("53080000", "IMPUESTO CRED LEY 25413"),
    "IMPUESTO A LOS DEB": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEBITOS TASA": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEBITOS ART 45": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEB LEY 25413": ("53070000", "IMPUESTO DEB LEY 25413"),
    "IVA ALICUOTA": ("11032050", "DGI IVA RET. Y PERCEPCIONES"),
    "SELLO": ("53010000", "GASTOS BANCARIOS"),
    "BANELCO": ("53010000", "GASTOS BANCARIOS"),
    "MANTENIMIENTO": ("53010000", "GASTOS BANCARIOS"),
    "COMISION": ("53010000", "GASTOS BANCARIOS"),
    "INTERES": ("51010000", "INTERESES BANCARIOS"),
    "DESCUBIERTO": ("51010000", "INTERESES BANCARIOS"),
    "HABERES": ("21012010", "PROVEEDORES"),
    "SUELDOS": ("21013010", "SUELDOS Y JORNALES A PAGAR"),
    "HONORARIOS": ("52020000", "HONORARIOS PROFESIONALES"),
    "DEPOSITO": ("11011000", "CAJA"),
    "CAJ AUT": ("11011000", "CAJA"),
    "RECIB": ("11031010", "DEUDORES POR SERVICIOS"),
    "DATAN": ("11031010", "DEUDORES POR SERVICIOS"),
    "OURENSE": ("11031010", "DEUDORES POR SERVICIOS"),
    "PAGO ELECTRONICO": ("21012010", "PROVEEDORES"),
    "PAGO DE SERVICIOS": ("21012010", "PROVEEDORES"),
    "PAGO DE CHEQUE": ("21012010", "PROVEEDORES"),
    "EBANKIN": ("21012010", "PROVEEDORES"),
    "TERCEROS": ("21012010", "PROVEEDORES"),
    "TRANSF": ("21012010", "PROVEEDORES"),
    "PROV": ("21012010", "PROVEEDORES"),
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

MARCA_SALTO_HOJA = "<<<SALTO_DE_HOJA>>>"

# Solo se usan si no se pudo ubicar la columna Débitos/Créditos del importe
CLAVES_CREDITO = ["RECIB", "DEPOSITO", "ACREDITADO", "CAJ AUT", "CVU", "TONELLI", "CPS", "OURENSE", "DATAN"]
CLAVES_DEBITO_FORZADO = ["IMPUESTO A LOS CRED", "CREDITOS TASA", "CRED LEY 25413"]

def normalizar(texto):
    """Mayúsculas, sin acentos y sin signos: 'Depósito Caj.Aut. Propio' -> 'DEPOSITO CAJ AUT PROPIO'"""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())

def asignar_cuenta(descripcion, es_credito, cuenta_puente):
    desc = " " + normalizar(descripcion) + " "
    tablas = [EQUIVALENCIAS_CREDITO, EQUIVALENCIAS_BASE] if es_credito else [EQUIVALENCIAS_BASE]
    for tabla in tablas:
        for clave, datos in tabla.items():
            if normalizar(clave) in desc:
                return str(datos[0]), str(datos[1])
    return str(cuenta_puente), "CUENTA PUENTE"

def es_importe(token):
    """True si el token tiene formato de importe: 1.234,56 / 1,25 / 1.234,56-"""
    return re.match(r'^-?\d{1,3}(\.\d{3})*,\d{2}-?$', token) is not None

def lineas_pdf(pdf):
    """Lee el PDF línea por línea. Cada línea es una lista de (palabra, borde derecho en la hoja),
    para saber en qué columna (Débitos / Créditos / Saldo) está cada importe."""
    salida = []
    for nro, page in enumerate(pdf.pages):
        if nro > 0:
            salida.append([(MARCA_SALTO_HOJA, None)])
        for l in page.extract_text_lines():
            tokens = l["text"].split()
            chars = [c for c in l.get("chars", []) if not c["text"].isspace()]
            coincide = sum(len(t) for t in tokens) == len(chars)
            fila, pos = [], 0
            for t in tokens:
                if coincide:
                    pos += len(t)
                    fila.append((t, chars[pos - 1]["x1"]))
                else:
                    fila.append((t, None))
            salida.append(fila)
    return salida

def procesar_lineas_comafi(filas):
    movimientos = []
    
    fecha_en_memoria = None
    concepto_acumulado = ""
    freno_activado = False
    en_corte_de_hoja = False  # entre el "Transporte" de una hoja y el primer importe de la siguiente
    movimiento_pendiente = False  # fecha + descripción sin importe, esperando el monto en la línea/hoja siguiente
    columnas_x = None  # posición de los encabezados Débitos / Créditos / Saldo
    
    def columna_de(x):
        if x is None or not columnas_x:
            return None
        return min(columnas_x, key=lambda k: abs(columnas_x[k] - x))
    
    for fila in filas:
        partes = [t for t, _ in fila]
        if len(partes) == 0:
            continue
        linea = " ".join(partes)
        linea_upper = linea.upper()
        
        # Salto de hoja: igual que antes, cada hoja arranca de cero...
        if linea.strip() == MARCA_SALTO_HOJA:
            freno_activado = False
            en_corte_de_hoja = True
            # ...SALVO que haya quedado un movimiento cortado (fecha al pie, importe en la hoja siguiente)
            if not movimiento_pendiente:
                fecha_en_memoria = None
                concepto_acumulado = ""
            continue
        
        # Encabezado de columnas: se guarda dónde están Débitos / Créditos / Saldo
        norm = [normalizar(t) for t in partes]
        if "DEBITOS" in norm and "CREDITOS" in norm and "SALDO" in norm:
            pos = {}
            for (t, x), n in zip(fila, norm):
                if n in ("DEBITOS", "CREDITOS", "SALDO") and x is not None:
                    pos[n] = x
            columnas_x = pos if len(pos) == 3 else columnas_x
            continue
        
        # "Transporte 0,00" solo cuando es la PRIMERA palabra de la línea
        # (antes se descartaba cualquier línea con "TRANSPORTE", como "OURENSE TRANSPORTES SA 2.600.000,00")
        if partes[0].upper() == "TRANSPORTE":
            en_corte_de_hoja = True
            continue
        
        if any(keyword in linea_upper for keyword in ["GARANTIA DE HASTA", "GARANTÍA DE HASTA", "LEY 24.485", "DECRETO 540/95", "CIRCULAR OPASI"]):
            continue 
            
        if "SALDO AL:" in linea_upper or "IMPUESTOS DEBITADOS" in linea_upper or "BASE IMPONIBLE" in linea_upper:
            freno_activado = True
            
        if freno_activado:
            movimiento_pendiente = False
            continue 
            
        # EXTRACCIÓN CORRECTA DE FECHA: Asegurar que se guarde como string puro de texto
        primer_token = str(partes[0])
        tiene_fecha = re.match(r'^\d{2}/\d{2}/\d{2}$', primer_token)
        hay_importe = any(es_importe(x) for x in partes)
        
        if tiene_fecha:
            fecha_en_memoria = primer_token
            en_corte_de_hoja = False
            if "Saldo Anterior" in linea:
                concepto_acumulado = ""
                movimiento_pendiente = False
                continue
            concepto_acumulado = " ".join([x for x in partes[1:] if not re.match(r'^\d{6,12}$', x) and "," not in x])
            movimiento_pendiente = not hay_importe
        else:
            if not fecha_en_memoria:
                continue
            # Entre hojas: encabezados y leyendas legales sin importe no se suman a la descripción
            if en_corte_de_hoja and not hay_importe:
                continue
            texto_secundario = " ".join([x for x in partes if not re.match(r'^\d{6,12}$', x) and "," not in x])
            if texto_secundario:
                concepto_acumulado += " " + texto_secundario

        importes_validos = []  # (valor, columna)
        for token, x in fila:
            if not es_importe(token):
                continue
            token_clean = token.replace(".", "").replace(",", ".")
            if token_clean.endswith("-"):
                token_clean = "-" + token_clean[:-1]
            importes_validos.append((float(token_clean), columna_de(x)))

        if not importes_validos:
            continue  
        
        en_corte_de_hoja = False
        desc_final = concepto_acumulado.strip()
        
        # Débito o crédito según la COLUMNA donde el banco puso el importe
        en_columna = [(v, c) for v, c in importes_validos if c in ("DEBITOS", "CREDITOS")]
        if en_columna:
            importe_real, col = en_columna[0]
            es_credito = (col == "CREDITOS")
        else:
            # Sin columnas detectadas: criterio anterior (penúltimo importe + palabras clave)
            valores = [v for v, _ in importes_validos]
            importe_real = valores[-2] if len(valores) >= 2 else valores[-1]
            desc_norm = normalizar(desc_final)
            es_credito = (any(kw in desc_norm for kw in CLAVES_CREDITO)
                          and not any(kw in desc_norm for kw in CLAVES_DEBITO_FORZADO))
            
        movimientos.append({
            "Fecha": str(fecha_en_memoria), # Forzado a texto plano
            "Descripción": desc_final,
            "Importe": abs(importe_real),
            "EsCredito": es_credito
        })
        concepto_acumulado = ""
        movimiento_pendiente = False
        
    return movimientos

if archivos_cargados:
    movimientos_totales = []
    
    for archivo in archivos_cargados:
        # Se procesa el PDF completo de una vez (no hoja por hoja) para no perder
        # movimientos cuya fecha queda al pie de una hoja y el importe en la siguiente
        with pdfplumber.open(archivo) as pdf:
            movimientos_totales.extend(procesar_lineas_comafi(lineas_pdf(pdf)))
                
    if movimientos_totales:
        df_origen = pd.DataFrame(movimientos_totales)
        st.success(f"🔥 ¡Éxito! Se procesaron {len(archivos_cargados)} archivos sueltos y se extrajeron {len(df_origen)} transacciones reales.")
        
        filas_planilla = []
        sin_cuenta = []
        asiento_actual = int(nro_asiento_inicial)
        fechas_unicas = df_origen["Fecha"].unique()
        
        for fecha in fechas_unicas:
            df_dia = df_origen[df_origen["Fecha"] == str(fecha)]
            pase_actual = 1
            
            for idx, fila in df_dia.iterrows():
                desc = fila["Descripción"]
                importe = fila["Importe"]
                es_credito = fila["EsCredito"]
                
                codigo_cuenta, nombre_cuenta = asignar_cuenta(desc, es_credito, cuenta_puente)
                if nombre_cuenta == "CUENTA PUENTE":
                    sin_cuenta.append({"Descripción": desc, "Tipo": "Crédito" if es_credito else "Débito", "Importe": importe})
                
                if es_credito:
                    monto_imputacion = -importe
                    monto_banco = float(importe)
                else:
                    monto_imputacion = float(importe)
                    monto_banco = -importe
                
                filas_planilla.append([int(asiento_actual), int(pase_actual), str(fecha), "Asiento Resumen Bancario", str(codigo_cuenta), float(monto_imputacion), 0.0, f"{nombre_cuenta} - {desc}", "", "", "", ""])
                pase_actual += 1
                
                filas_planilla.append([int(asiento_actual), int(pase_actual), str(fecha), "Asiento Resumen Bancario", str(CUENTA_BANCO_COMAFI), float(monto_banco), 0.0, f"COMAFI CTA CTE - {desc}", "", "", "", ""])
                pase_actual += 1
                
            asiento_actual += 1
            
        columnas_onvio = [
            "Número de asiento", "Número de Pase", "Fecha", "Concepto", "Código de cuenta",
            "Importe en moneda local", "Importe en moneda ext.present.", "Leyenda",
            "Código de centro de costos", "Porcentaje de distribución", 
            "Imp.mon.local dist.C.Costos", "Imp.mon.present.dist.C.Costos"
        ]
        
        df_resultado = pd.DataFrame(filas_planilla, columns=columnas_onvio)
        
        if not df_resultado.empty:
            st.markdown("### 2. Previsualización y Control")
            if sin_cuenta:
                df_sin = (pd.DataFrame(sin_cuenta).groupby(["Descripción", "Tipo"], as_index=False)
                          .agg(Movimientos=("Importe", "size"), Total=("Importe", "sum"))
                          .sort_values("Movimientos", ascending=False))
                st.warning(f"⚠️ {len(sin_cuenta)} movimientos quedaron en Cuenta Puente ({cuenta_puente}). "
                           "Agregá su texto en las equivalencias para imputarlos.")
                with st.expander("Ver descripciones que fueron a Cuenta Puente"):
                    st.dataframe(df_sin, use_container_width=True, hide_index=True)
            st.dataframe(df_resultado)
            
            st.markdown("### 3. Exportación Final")
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_resultado.to_excel(writer, index=False, sheet_name='Importacion_ONVIO')
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 Descargar Excel para importar en ONVIO",
                data=excel_data,
                file_name=f"Importacion_ONVIO_{pd.Timestamp.today():%Y%m%d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    else:
        st.warning("⚠️ No se encontraron movimientos en los PDFs cargados.")
