import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

st.set_page_config(page_title="Automatizador Contable - Sector Sociedades", layout="wide")

st.title("🤖 Sistema de Automatización Contable")
st.subheader("Asociaciones Civiles - Motor de Importación Directa para 'ONVIO'")

# 1. CUENTAS CONTABLES FIJAS (Plan de Cuentas Real)
CUENTA_BANCO_COMAFI = "11016010"  # CTA/CTE $ COMAFI 1070-01085-6
CUENTA_PUENTE_DEF = "13000000"

# 2. MAPEO DEFINITIVO DE EQUIVALENCIAS CONTABLES
EQUIVALENCIAS_BASE = {
    "MANTENIMIENTO DE": ("53010000", "GASTOS BANCARIOS"),
    "COMISION EMISION": ("53010000", "GASTOS BANCARIOS"),
    "COMISION TRANSFERENCIAS": ("53010000", "GASTOS BANCARIOS"),
    "COMISION": ("53010000", "GASTOS BANCARIOS"),
    "PAGO DE CHEQUE POR CAJA": ("21012010", "PROVEEDORES"),
    "PAGO DE CHEQUE 48 HS": ("21012010", "PROVEEDORES"),
    "PAGO DE SERVICIOS POR PAGO DIR": ("21012010", "PROVEEDORES"),
    "DEPOSITO DE CHEQUES 48 HS": ("21012010", "PROVEEDORES"),
    "DEPOSITO DE EFECTIVO": ("11011000", "CAJA"),
    "DEPOSITO EN CAJERO AUTOMATICO": ("11011000", "CAJA"),
    "DEBITOS - TASA": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEBITOS ART 45": ("53070000", "IMPUESTO DEB LEY 25413"),
    "DEB LEY 25413": ("53070000", "IMPUESTO DEB LEY 25413"),
    "IMPUESTO A LOS DEBITOS": ("53070000", "IMPUESTO DEB LEY 25413"),
    "CREDITOS-TASA G": ("53080000", "IMPUESTO CRED LEY 25413"),
    "CRED LEY 25413": ("53080000", "IMPUESTO CRED LEY 25413"),
    "IMPUESTO A LOS CREDITOS": ("53080000", "IMPUESTO CRED LEY 25413"),
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
cuenta_puente = st.sidebar.text_input("Cuenta Puente", value=CUENTA_PUENTE_DEF)

st.markdown("### 1. Cargar Extracto Bancario Obligatorio")
archivo_cargado = st.file_uploader("Arrastrá el PDF original del Banco Comafi", type=["pdf"])

def procesar_lineas_comafi(text):
    movimientos = []
    lineas = text.split("\n")
    
    for linea in lineas:
        partes = linea.split()
        if len(partes) < 3:
            continue
            
        # Validar si arranca con fecha (DD/MM/YY)
        if not re.match(r'^\d{2}/\d{2}/\d{2}$', partes[0]):
            continue
            
        fecha = partes[0]
        if "Saldo Anterior" in linea:
            continue
            
        # Separar tokens financieros (importes con decimales) de números de referencia (enteros largos)
        importes_validos = []
        tokens_descripcion = []
        
        for token in partes[1:]:
            # Si el token cumple con la estructura de un número largo de referencia contable (6 a 12 dígitos puros)
            if re.match(r'^\d{6,12}$', token):
                continue  # Ignoramos la referencia para que no interfiera con los montos
                
            token_clean = token.replace(".", "").replace(",", ".")
            if token_clean.endswith("-"):
                token_clean = "-" + token_clean[:-1]
                
            try:
                # Comprobamos si tiene formato de importe contable argentino (ej: 300,00 o 15.985,00 con la coma decimal)
                if "," in token:
                    val = float(token_clean)
                    importes_validos.append(val)
                else:
                    tokens_descripcion.append(token)
            except ValueError:
                tokens_descripcion.append(token)

        if not importes_validos:
            continue
            
        # Evaluación inteligente según la cantidad de columnas de dinero detectadas en la línea
        # Si la línea tiene Saldo al final, posee 2 o más importes: el anteúltimo es el importe real.
        # Si la línea no tiene Saldo al final, el único importe detectado es el valor real de la transacción.
        if len(importes_validos) >= 2:
            importe_real = importes_validos[-2]
        else:
            importe_real = importes_validos[0]
            
        descripcion = " ".join(tokens_descripcion)
        
        # Determinar el sentido del movimiento basándonos en el concepto contable
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
        st.success(f"Se extrajeron correctamente {len(df_origen)} transacciones reales del PDF.")
        
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
                        codigo_cuenta = datos
                        nombre_cuenta = datos
                        break
                
                # Definición estricta de signos de acuerdo a la naturaleza contable
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

