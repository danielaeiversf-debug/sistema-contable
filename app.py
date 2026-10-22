import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

st.set_page_config(page_title="Automatizador Contable - Sector Sociedades", layout="wide")

st.title("🤖 Sistema de Automatización Contable")
st.subheader("Asociaciones Civiles - Motor de Importación Directa para 'ONVIO'")

# 1. CUENTAS CONTABLES FIJAS (Plan de Cuentas)
CUENTA_BANCO_COMAFI = "11016010"  # CTA/CTE $ COMAFI 1070-01085-6
CUOTA_PUENTE_DEF = "13000000"

# 2. DICCIONARIO RE-CALIBRADO CON TUS ESPECIFICACIONES EXACTAS
EQUIVALENCIAS_BASE = {
    "MANTENIMIENTO DE": ("53010000", "GASTOS BANCARIOS"),
    "COMISION": ("53010000", "GASTOS BANCARIOS"),
    "PAGO DE CHEQUE POR CAJA": ("21012010", "PROVEEDORES"),
    "PAGO DE CHEQUE 48 HS": ("21012010", "PROVEEDORES"),
    "DEPOSITO DE CHEQUES 48 HS": ("21012010", "PROVEEDORES"),
    "DEPOSITO DE EFECTIVO": ("11011000", "CAJA"),
    "DEPOSITO EN CAJERO AUTOMATICO": ("11011000", "CAJA"),
    "DEBITOS - TASA": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEBITOS ART 45": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEB LEY 25413": ("53070000", "IMPUESTO DEB LEY 25413"),
    "CREDITOS-TASA G": ("53080000", "IMPUESTO CRED LEY 25413"),
    "CRED LEY 25413": ("53080000", "IMPUESTO CRED LEY 25413"),
    "IVA - ALICUOTA": ("11032050", "DGI IVA RET. Y PERCEPCIONES"),
    "SUELDOS": ("21013010", "SUELDOS Y JORNALES A PAGAR"),
    "TRANSFERENCIA TERCEROS EBANKIN": ("21012010", "PROVEEDORES"),
    "TRANSF. INMEDIATA RECIBIDA": ("11031010", "DEUDORES POR SERVICIOS"),
    "TRANSFERENCIA TERCEROS RECIBID": ("11031010", "DEUDORES POR SERVICIOS"),
    "HONORARIOS": ("52020000", "HONORARIOS PROFESIONALES"),
}

# Configuración en la barra lateral
st.sidebar.header("⚙️ Parámetros de Importación ONVIO")
nro_asiento_inicial = st.sidebar.number_input("Número de Asiento Inicial", min_value=1, value=1, step=1)
cuenta_puente = st.sidebar.text_input("Cuenta Puente", value=CUOTA_PUENTE_DEF)

st.markdown("### 1. Cargar Extracto Bancario Obligatorio")
archivo_cargado = st.file_uploader("Arrastrá el PDF original del Banco Comafi", type=["pdf"])

def procesar_lineas_comafi(text):
    movimientos = []
    lineas = text.split("\n")
    
    for linea in lineas:
        partes = linea.split()
        if len(partes) < 3:
            continue
            
        # Validar si arranca con fecha DD/MM/YY
        if not re.match(r'^\d{2}/\d{2}/\d{2}$', partes[0]):
            continue
            
        fecha = partes[0]
        if "Saldo Anterior" in linea:
            continue
            
        # Filtrar todos los números reales de la línea (con decimales)
        numeros_encontrados = []
        for p in partes[1:]:
            p_clean = p.replace(".", "").replace(",", ".")
            if p_clean.endswith("-"):
                p_clean = "-" + p_clean[:-1]
            try:
                val = float(p_clean)
                # Las referencias bancarias suelen ser enteros largos sin coma. 
                # Evaluamos si tiene decimales significativos o si está en la posición de importes.
                numeros_encontrados.append((val, p))
            except ValueError:
                continue

        if len(numeros_encontrados) < 2:
            continue
            
        # En Comafi, el último valor es SIEMPRE el Saldo. El ANTEÚLTIMO es el Importe real de Débito/Crédito.
        # Esto descarta de forma matemática cualquier número de referencia previo.
        importe_real = numeros_encontrados[-2][0]
        saldo_real = numeros_encontrados[-1][0]
        
        # Aislar la descripción eliminando la fecha y los números del final
        str_numeros_finales = [numeros_encontrados[-2][1], numeros_encontrados[-1][1]]
        descripcion = " ".join([x for x in partes[1:] if x not in str_numeros_finales and not re.match(r'^\d{6,12}$', x)])
        
        # Determinar dirección del movimiento
        es_credito = False
        desc_upper = descripcion.upper()
        if any(kw in desc_upper for kw in ["RECIBIDA", "CREDITOS", "DEPOSITO", "ACREDITADO", "RECIBID"]):
            es_credito = True
            
        movimientos.append({
            "Fecha": fecha,
            "Descripción": descripcion.strip(),
            "Importe": abs(importe_real),
            "EsCredito": es_credito
        })
    return movimientos

if archivo_cargado is not None:
    movimientos_limpios = []
    with pdfplumber.open(archivo_cargado) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                movimientos_limpios.extend(procesar_lineas_comafi(text))
                
    df_origen = pd.DataFrame(movimientos_limpios)

    if not df_origen.empty:
        st.success(f"Se extrajeron correctamente {len(df_origen)} transacciones del PDF.")
        
        df_origen["Fecha_DT"] = pd.to_datetime(df_origen["Fecha"], format="%d/%m/%y", errors='coerce')
        df_origen = df_origen.sort_values(by="Fecha_DT").drop(columns=["Fecha_DT"])
        
        asientos_onvio = []
        asiento_actual = nro_asiento_inicial
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
                
                # Regla de signos ONVIO balanceada
                if es_credito:
                    monto_imputacion = -importe
                    monto_banco = importe
                else:
                    monto_imputacion = importe
                    monto_banco = -importe
                
                # Pase 1: Cuenta Destino Imputada
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
                
            asiento_actual += 1
            
        df_resultado = pd.DataFrame(asientos_onvio)
        
        if not df_resultado.empty:
            st.write("#### Previsualización de la planilla estructurada para ONVIO:")
            st.dataframe(df_resultado)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_resultado.to_excel(writer, index=False, sheet_name='Importacion_ONVIO')
            excel_data = output.getvalue()
            
            st.markdown("### 3. Exportación Final")
            st.download_button(
                label="📥 Descargar Archivo para Subir a ONVIO",
                data=excel_data,
                file_name="asientos_listos_onvio.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("No se detectaron movimientos contables válidos en el archivo.")
