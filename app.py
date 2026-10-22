import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

st.set_page_config(page_title="Automatizador Contable - Sector Sociedades", layout="wide")

st.title("🤖 Sistema de Automatización Contable")
st.subheader("Asociaciones Civiles - Motor de Importación Directa para 'ONVIO'")

# 1. CUENTAS CONTABLES FIJAS (Extraídas de tu Plan de Cuentas)
CUENTA_BANCO_COMAFI = "11016010"  # CTA/CTE $ COMAFI 1070-01085-6

# 2. DICCIONARIO INTELIGENTE DE EQUIVALENCIAS
EQUIVALENCIAS_BASE = {
    "DEB LEY 25413": ("53070000", "IMPUESTO DEB LEY 25413"),
    "CRED LEY 25413": ("53080000", "IMPUESTO CRED LEY 25413"),
    "DEBITOS - TASA": ("53070000", "IMPUESTO DEB LEY 25413"),
    "CREDITOS-TASA G": ("53080000", "IMPUESTO CRED LEY 25413"),
    "DEBITOS ART 45": ("53070000", "IMPUESTO DEB LEY 25413"),
    "COMISION": ("53010000", "GASTOS BANCARIOS"),
    "IVA - ALICUOTA": ("11032050", "DGI IVA RET. Y PERCEPCIONES"), # O la que corresponda a su IVA CF
    "SUELDOS": ("21013010", "SUELDOS Y JORNALES A PAGAR"),
    "PROV": ("21012010", "PROVEEDORES"),
    "HONORARIOS": ("52020000", "HONORARIOS PROFESIONALES"),
    "DONACION": ("43020000", "DONACIONES"),
    "SUBSIDIO": ("42070000", "SUBSIDIOS")
}

# Configuración en la barra lateral
st.sidebar.header("⚙️ Parámetros de Importación ONVIO")
nro_asiento_inicial = st.sidebar.number_input("Número de Asiento Inicial", min_value=1, value=1, step=1)
cuenta_puente = st.sidebar.text_input("Cuenta Puente (Sin coincidencia)", value="13000000")

st.markdown("### 1. Cargar Extracto Bancario Obligatorio")
archivo_cargado = st.file_uploader("Arrastrá el PDF original del Banco Comafi", type=["pdf", "xlsx", "xls", "csv"])

def parsear_renglon_comafi(linea):
    """
    Parsea una línea del extracto Comafi detectando Fecha, Concepto y montos de Débito/Crédito.
    Ignora el saldo final de la línea evaluando las últimas columnas.
    """
    partes = linea.split()
    if len(partes) < 3:
        return None
        
    # Verificar si el renglón arranca con una fecha válida (DD/MM/YY)
    match_fecha = re.match(r'^\d{2}/\d{2}/\d{2}$', partes[0])
    if not match_fecha:
        return None
        
    fecha = partes[0]
    
    # Tratamiento especial si dice "Saldo Anterior"
    if "Saldo Anterior" in linea:
        return None # No genera asiento de movimiento diario
        
    # Intentar identificar números al final de la línea (Débitos, Créditos, Saldo)
    # Buscamos los bloques numéricos con formato de moneda de atrás hacia adelante
    valores_numericos = []
    indices_numericos = []
    
    for idx in reversed(range(1, len(partes))):
        token = partes[idx]
        # Limpieza visual para validar si es un número válido contable
        token_clean = token.replace(".", "").replace(",", ".")
        # Manejo de saldos negativos que terminan con guión (ej: 65.093,48-)
        if token_clean.endswith("-"):
            token_clean = "-" + token_clean[:-1]
        try:
            val = float(token_clean)
            valores_numericos.insert(0, val)
            indices_numericos.insert(0, idx)
        except ValueError:
            break # Parar si ya no es un número financiero
            
    if len(valores_numericos) < 2:
        return None # Necesitamos al menos el importe del movimiento y el saldo para discriminar
        
    # El último valor de la línea SIEMPRE es el Saldo acumulado, lo descartamos.
    saldo_descartado = valores_numericos[-1]
    importes_movimiento = valores_numericos[:-1]
    
    # Reconstruir la descripción removiendo la fecha y los importes finales
    idx_corte_desc = indices_numericos[0]
    descripcion = " ".join(partes[1:idx_corte_desc])
    
    # Determinar si es egreso (Débito) o ingreso (Crédito) basándonos en la estructura del PDF
    # Si hay un único importe antes del saldo, evaluamos palabras clave comunes o su posición relativas si es posible.
    # Para Comafi nativo, si viene de la sección ordinaria de movimientos:
    importe_final = importes_movimiento[-1]
    
    es_credito = False
    desc_upper = descripcion.upper()
    if "RECIBIDA" in desc_upper or "CREDITOS" in desc_upper or "DEPOSITO" in desc_upper or "ACREDITADO" in desc_upper:
        es_credito = True
        
    return {
        "Fecha": fecha,
        "Descripción": descripcion,
        "Importe": importe_final,
        "EsCredito": es_credito
    }

if archivo_cargado is not None:
    ext = archivo_cargado.name.split(".")[-1].lower()
    movimientos_limpios = []
    
    if ext == "pdf":
        with pdfplumber.open(archivo_cargado) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    for linea in text.split("\n"):
                        res = parsear_renglon_comafi(linea)
                        if res:
                            movimientos_limpios.append(res)
        df_origen = pd.DataFrame(movimientos_limpios)
    else:
        st.warning("Para garantizar la precisión de las columnas de Débitos/Créditos, por favor suba el archivo en formato PDF original.")
        df_origen = pd.DataFrame()

    if not df_origen.empty:
        st.success(f"Se extrajeron correctamente {len(df_origen)} transacciones del PDF.")
        
        # ORDENAR POR FECHA PARA GARANTIZAR LA CORRELATIVIDAD DE ONVIO
        df_origen["Fecha_DT"] = pd.to_datetime(df_origen["Fecha"], format="%d/%m/%y", errors='coerce')
        df_origen = df_origen.sort_values(by="Fecha_DT").drop(columns=["Fecha_DT"])
        
        asientos_onvio = []
        asiento_actual = nro_asiento_inicial
        
        # Agrupar movimientos por fecha para cumplir la regla de ONVIO
        fechas_unicas = df_origen["Fecha"].unique()
        
        for fecha in fechas_unicas:
            df_dia = df_origen[df_origen["Fecha"] == fecha]
            pase_actual = 1
            
            for idx, fila in df_dia.iterrows():
                desc = fila["Descripción"]
                importe = fila["Importe"]
                es_credito = fila["EsCredito"]
                
                desc_upper = desc.upper()
                codigo_cuenta = cuenta_puente
                nombre_cuenta = "CUENTA PUENTE REVISAR"
                
                for clave, datos in EQUIVALENCIAS_BASE.items():
                    if clave in desc_upper:
                        codigo_cuenta = datos[0]
                        nombre_cuenta = datos[1]
                        break
                
                # Definición de signos contables según la naturaleza del movimiento
                if es_credito:
                    # Es un ingreso (Crédito bancario): entra plata al banco (+) y sale de la imputación (-)
                    monto_imputacion = -importe
                    monto_banco = importe
                else:
                    # Es un egreso (Débito bancario): suma el gasto (+) y resta del banco (-)
                    monto_imputacion = importe
                    monto_banco = -importe
                
                # Pase 1: Cuenta Imputada del Plan de Cuentas
                asientos_onvio.append({
                    "Número de asiento": asiento_actual,
                    "Número de Pase": pase_actual,
                    "Fecha": fecha,
                    "Concepto": "Asiento Resumen Bancario",
                    "Código de cuenta": codigo_cuenta,
                    "Importe en moneda local": monto_imputacion,
                    "Importe en moneda ext.present.": 0.0,
                    "Leyenda": f"{nombre_cuenta} - {desc}",
                    "Código de centro de costos": "",
                    "Porcentaje de distribución": "",
                    "Imp.mon.local dist.C.Costos": "",
                    "Imp.mon.present.dist.C.Costos": ""
                })
                pase_actual += 1
                
                # Pase 2: Contrapartida de Banco Comafi
                asientos_onvio.append({
                    "Número de asiento": asiento_actual,
                    "Número de Pase": pase_actual,
                    "Fecha": fecha,
                    "Concepto": "Asiento Resumen Bancario",
                    "Código de cuenta": CUENTA_BANCO_COMAFI,
                    "Importe en moneda local": monto_banco,
                    "Importe en moneda ext.present.": 0.0,
                    "Leyenda": f"COMAFI CTA CTE - {desc}",
                    "Código de centro de costos": "",
                    "Porcentaje de distribución": "",
                    "Imp.mon.local dist.C.Costos": "",
                    "Imp.mon.present.dist.C.Costos": ""
                })
                pase_actual += 1
                
            # Finalizado el día, el próximo día cambia de número de asiento
            asiento_actual += 1
            
        df_resultado = pd.DataFrame(asientos_onvio)
        
        if not df_resultado.empty:
            st.write("#### Previsualización de la planilla estructurada para ONVIO:")
            st.dataframe(df_resultado)
            
            # Validación global del Debe y el Haber
            suma_total = df_resultado["Importe en moneda local"].sum()
            if abs(suma_total) < 0.01:
                st.success("✅ Validación Exitosa: El archivo está perfectamente balanceado para ONVIO.")
            else:
                st.error(f"⚠️ Error de balanceo: La suma total difiere por {suma_total}. Verifique los signos.")
                
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_resultado.to_excel(writer, index=False, sheet_name='Importacion_ONVIO')
            excel_data = output.getvalue()
            
            st.markdown("### 3. Exportación Final")
            st.download_button(
                label="📥 Descargar Archivo para Subir a ONVIO",
                data=excel_data,
                file_name="asientos_listos_onvio.xlsx",
