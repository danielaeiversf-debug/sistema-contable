import streamlit as st
import pandas as pd
import pdfplumber
import io
import re
import json
import unicodedata
from pathlib import Path

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

# 2. CONFIGURACIÓN POR EMPRESA Y BANCO (carpeta "datos" del repositorio)
#    datos/empresas.json  -> empresas, sus bancos, cuenta contable del banco y texto del Concepto
#    datos/planes/*.csv   -> plan de cuentas de cada empresa (codigo;descripcion)
#    datos/reglas/*.csv   -> reglas de imputación por empresa + banco (texto;tipo;cuenta;nombre)
CARPETA_APP = Path(__file__).parent
CARPETA_DATOS = CARPETA_APP / "datos"
CUENTA_PUENTE_DEF = "13000000"

def ubicar_archivo(ruta_relativa):
    """Busca el archivo en datos/<ruta>; si no está ahí, lo busca por nombre en todo el repositorio
    (por si la carpeta se subió con otro nombre o los archivos quedaron sueltos)."""
    ruta = CARPETA_DATOS / ruta_relativa
    if ruta.exists():
        return ruta
    nombre = Path(ruta_relativa).name
    for candidato in sorted(CARPETA_APP.rglob(nombre)):
        if ".git" not in candidato.parts:
            return candidato
    st.error(f"❌ No se encontró el archivo **{nombre}** en el repositorio. "
             f"Subí la carpeta `datos` completa (con `empresas.json`, `planes/` y `reglas/`) al lado de `app.py`.")
    st.stop()

def normalizar(texto):
    """Mayúsculas, sin acentos y sin signos: 'Depósito Caj.Aut. Propio' -> 'DEPOSITO CAJ AUT PROPIO'"""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())

@st.cache_data
def cargar_empresas():
    with open(ubicar_archivo("empresas.json"), encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def cargar_plan(ruta):
    """Devuelve {codigo: descripcion} y el conjunto de cuentas imputables (las que no son títulos)."""
    if not ruta:
        return {}, set()
    df = pd.read_csv(ubicar_archivo(ruta), sep=";", dtype=str, encoding="utf-8-sig").dropna()
    plan = dict(zip(df["codigo"].str.strip(), df["descripcion"].str.strip()))
    titulos = set()
    for cod in plan:
        prefijo = cod.rstrip("0")
        if any(otro != cod and otro.startswith(prefijo) for otro in plan):
            titulos.add(cod)
    return plan, set(plan) - titulos

@st.cache_data
def cargar_reglas(ruta):
    df = pd.read_csv(ubicar_archivo(ruta), sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    return [{"texto": normalizar(r["texto"]), "tipo": r["tipo"].strip().upper(),
             "cuenta": r["cuenta"].strip(), "nombre": r["nombre"].strip()} for _, r in df.iterrows()]

def validar_reglas(reglas, plan, imputables):
    """Avisa si una regla apunta a un código que no está en el plan o que es un título."""
    if not plan:
        return []
    errores = []
    for r in reglas:
        if r["cuenta"] == "PUENTE":
            continue
        if r["cuenta"] not in plan:
            errores.append(f"'{r['texto']}' → {r['cuenta']}: el código no existe en el plan de cuentas")
        elif r["cuenta"] not in imputables:
            errores.append(f"'{r['texto']}' → {r['cuenta']} ({plan[r['cuenta']]}): es una cuenta título, no imputable")
    return errores

def asignar_cuenta(descripcion, es_credito, reglas, plan, cuenta_puente):
    """Recorre las reglas en orden; gana la primera cuyo texto aparece (al inicio de una palabra)
    en la descripción y cuyo tipo coincide (DEBITO / CREDITO / AMBOS)."""
    desc = " " + normalizar(descripcion) + " "
    tipo_mov = "CREDITO" if es_credito else "DEBITO"
    for r in reglas:
        if r["tipo"] not in ("AMBOS", tipo_mov):
            continue
        if " " + r["texto"] in desc:
            if r["cuenta"] == "PUENTE":
                return str(cuenta_puente), "CUENTA PUENTE (TRANSF. CUENTA PROPIA)", True
            nombre = plan.get(r["cuenta"]) or r["nombre"] or r["cuenta"]
            return r["cuenta"], nombre, True
    return str(cuenta_puente), "CUENTA PUENTE", False

EMPRESAS = cargar_empresas()

# Barra lateral: empresa y banco
st.sidebar.header("⚙️ Selección de Entorno de Trabajo")
empresa_seleccionada = st.sidebar.selectbox("Seleccionar Empresa Cliente", list(EMPRESAS.keys()))
empresa = EMPRESAS[empresa_seleccionada]
banco_activo = st.sidebar.selectbox("Seleccionar Banco", list(empresa["bancos"].keys()))
banco = empresa["bancos"][banco_activo]
nro_asiento_inicial = st.sidebar.number_input("Número de Asiento Inicial", min_value=1, value=1, step=1)
cuenta_puente = st.sidebar.text_input("Cuenta Puente", value=CUENTA_PUENTE_DEF)

cuenta_banco_activa = banco["cuenta_contable"]
plan_activo, imputables = cargar_plan(empresa.get("plan_de_cuentas", ""))
reglas_activas = cargar_reglas(banco["reglas"])

nombre_cuenta_banco = plan_activo.get(cuenta_banco_activa, "")
st.sidebar.info(f"🏦 Banco: {banco_activo}\n💳 Cuenta contable: {cuenta_banco_activa} {nombre_cuenta_banco}\n"
                f"📒 Plan de cuentas: {f'{len(plan_activo)} cuentas' if plan_activo else 'sin cargar (nombres desde las reglas)'}")

if st.sidebar.button("🔒 Cerrar Sesión"):
    st.session_state["autenticado"] = False
    st.rerun()

errores_reglas = validar_reglas(reglas_activas, plan_activo, imputables)
if plan_activo and cuenta_banco_activa not in plan_activo:
    errores_reglas.insert(0, f"La cuenta del banco {cuenta_banco_activa} no existe en el plan de cuentas")
if errores_reglas:
    st.error("⚠️ Hay reglas de imputación que no coinciden con el plan de cuentas:\n\n- " + "\n- ".join(errores_reglas))

st.markdown(f"### 1. Cargar Extractos de: **{empresa_seleccionada}** ({banco_activo})")
archivos_cargados = st.file_uploader("Arrastrá uno o más PDFs del extracto bancario a la vez", type=["pdf"], accept_multiple_files=True)

MARCA_SALTO_HOJA = "<<<SALTO_DE_HOJA>>>"

# Solo se usan si no se pudo ubicar la columna Débitos/Créditos del importe (Comafi)
CLAVES_CREDITO = ["RECIB", "DEPOSITO", "ACREDITADO", "CAJ AUT", "CVU", "TONELLI", "CPS", "OURENSE", "DATAN"]
CLAVES_DEBITO_FORZADO = ["IMPUESTO A LOS CRED", "CREDITOS TASA", "CRED LEY 25413"]

# --- MOTOR DE LECTURA COMAFI ---
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
        try:
            lineas_pagina = page.extract_text_lines()
        except Exception:
            # Respaldo: lectura simple de texto (sin posición de columnas)
            lineas_pagina = [{"text": t, "chars": []} for t in (page.extract_text() or "").split("\n")]
        for l in lineas_pagina:
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

# --- MOTOR DE LECTURA GALICIA ---
def procesar_galicia(pdf, cuit_propio=""):
    """Lee el extracto de Cuenta Corriente del Galicia.
    - Cada movimiento empieza con fecha y termina con importe y saldo (débitos con signo negativo).
    - Las líneas siguientes sin fecha completan la descripción (ej.: ACREDITAMIENTO / PRISMA-COMERCIOS / VISA EST.).
    - Si el detalle trae el CUIT de la propia empresa, se marca como CUENTA PROPIA.
    Devuelve (movimientos, totales_del_extracto)."""
    movimientos = []
    actual = None
    totales = None
    fin_movimientos = False
    patron_mov = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(.*?)\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})$')
    patron_total = re.compile(r'^Total\s+\$\s*([\d.]+,\d{2})\s+-?\$\s*([\d.]+,\d{2})')

    def a_float(s):
        return float(s.replace(".", "").replace(",", "."))

    def cerrar(mov):
        if mov is None:
            return
        extra = " ".join(mov["extra"])
        tokens = [x for x in (mov["desc"] + " " + extra).split() if not re.match(r'^\d{6,}$', x)]
        desc = " ".join(tokens)
        # Transferencia cuyo ordenante/destinatario es la propia empresa (mismo CUIT) = transferencia entre cuentas propias
        if (cuit_propio and "TRANSF" in mov["desc"].upper()
                and cuit_propio in (mov["desc"] + " " + extra).replace("-", "")):
            desc += " CUENTA PROPIA"
        movimientos.append({"Fecha": mov["fecha"], "Descripción": desc,
                            "Importe": abs(mov["importe"]), "EsCredito": mov["importe"] > 0})

    for page in pdf.pages:
        for linea in (page.extract_text() or "").split("\n"):
            l = linea.strip()
            if not l or fin_movimientos:
                continue
            m_total = patron_total.match(l)
            if m_total:
                totales = (a_float(m_total.group(1)), a_float(m_total.group(2)))
                cerrar(actual); actual = None
                fin_movimientos = True
                continue
            u = l.upper()
            if "CONSOLIDADO DE RETENC" in u:
                cerrar(actual); actual = None
                fin_movimientos = True
                continue
            # Encabezados y pies de página
            if u.startswith("RESUMEN DE CUENTA") or u.startswith("FECHA DESCRIPCI") or re.match(r'^\d{14,}[A-Z]?$', l):
                continue
            m = patron_mov.match(l)
            if m:
                cerrar(actual)
                actual = {"fecha": m.group(1), "desc": m.group(2), "importe": a_float(m.group(3)), "extra": []}
            elif actual is not None:
                actual["extra"].append(l)
    cerrar(actual)
    return movimientos, totales

# --- PROCESAMIENTO PRINCIPAL ---
if archivos_cargados:
    movimientos_totales = []
    controles = []
    
    for archivo in archivos_cargados:
        with pdfplumber.open(archivo) as pdf:
            if banco["lector"] == "galicia":
                movs, totales = procesar_galicia(pdf, empresa.get("cuit", ""))
                movimientos_totales.extend(movs)
                if totales:
                    cred = round(sum(m["Importe"] for m in movs if m["EsCredito"]), 2)
                    deb = round(sum(m["Importe"] for m in movs if not m["EsCredito"]), 2)
                    controles.append((archivo.name, cred, deb, totales[0], totales[1]))
            else:
                # Se procesa el PDF completo de una vez (no hoja por hoja) para no perder
                # movimientos cuya fecha queda al pie de una hoja y el importe en la siguiente
                movimientos_totales.extend(procesar_lineas_comafi(lineas_pdf(pdf)))
                
    if movimientos_totales:
        df_origen = pd.DataFrame(movimientos_totales)
        st.success(f"🔥 ¡Éxito! Se procesaron {len(archivos_cargados)} archivos y se extrajeron {len(df_origen)} transacciones reales.")
        
        # Control de totales contra el pie del extracto (Galicia)
        for nombre, cred, deb, tot_cred, tot_deb in controles:
            if abs(cred - tot_cred) < 0.01 and abs(deb - tot_deb) < 0.01:
                st.info(f"✅ {nombre}: créditos $ {cred:,.2f} y débitos $ {deb:,.2f} coinciden con los totales del extracto.")
            else:
                st.error(f"❌ {nombre}: créditos $ {cred:,.2f} (extracto $ {tot_cred:,.2f}) · débitos $ {deb:,.2f} "
                         f"(extracto $ {tot_deb:,.2f}). Revisar movimientos.")
        
        filas_planilla = []
        sin_cuenta = []
        asiento_actual = int(nro_asiento_inicial)
        fechas_unicas = df_origen["Fecha"].unique()
        
        for fecha in fechas_unicas:
            df_dia = df_origen[df_origen["Fecha"] == str(fecha)]
            pase_actual = 1
            
            # Concepto: BCO ... CTA CTE $ N° MES MM/AAAA (según la fecha del asiento)
            _d, _m, _a = str(fecha).split("/")
            concepto_asiento = f"{banco['concepto']} MES {_m}/{'20' + _a if len(_a) == 2 else _a}"
            
            for idx, fila in df_dia.iterrows():
                desc = fila["Descripción"]
                importe = fila["Importe"]
                es_credito = fila["EsCredito"]
                
                codigo_cuenta, nombre_cuenta, con_regla = asignar_cuenta(desc, es_credito, reglas_activas, plan_activo, cuenta_puente)
                if not con_regla:
                    sin_cuenta.append({"Descripción": desc, "Tipo": "Crédito" if es_credito else "Débito", "Importe": importe})
                
                if es_credito:
                    monto_imputacion = -importe
                    monto_banco = float(importe)
                else:
                    monto_imputacion = float(importe)
                    monto_banco = -importe
                
                filas_planilla.append([int(asiento_actual), int(pase_actual), str(fecha), concepto_asiento, str(codigo_cuenta), float(monto_imputacion), 0.0, f"{nombre_cuenta} - {desc}", "", "", "", ""])
                pase_actual += 1
                
                filas_planilla.append([int(asiento_actual), int(pase_actual), str(fecha), concepto_asiento, str(cuenta_banco_activa), float(monto_banco), 0.0, f"{banco['leyenda_banco']} - {desc}", "", "", "", ""])
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
                           "Agregá su texto en las reglas de imputación para imputarlos.")
                with st.expander("Ver descripciones que fueron a Cuenta Puente"):
                    st.dataframe(df_sin, use_container_width=True, hide_index=True)
            st.dataframe(df_resultado)
            
            st.markdown("### 3. Exportación Final")
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_resultado.to_excel(writer, index=False, sheet_name='Importacion_ONVIO')
                # Encabezados con fondo naranja
                from openpyxl.styles import PatternFill
                relleno_naranja = PatternFill(start_color="FFA500", end_color="FFA500", fill_type="solid")
                for celda in writer.sheets['Importacion_ONVIO'][1]:
                    celda.fill = relleno_naranja
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 Descargar Excel para importar en ONVIO",
                data=excel_data,
                file_name=f"Importacion_ONVIO_{empresa_seleccionada.replace(' ', '_')}_{banco_activo.replace(' ', '_')}_{pd.Timestamp.today():%Y%m%d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    else:
        st.warning("⚠️ No se encontraron movimientos en los PDFs cargados.")
