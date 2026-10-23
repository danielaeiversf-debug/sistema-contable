import streamlit as st
import pandas as pd
import pdfplumber
import io
import re

st.set_page_config(page_title="Automatizador Contable - Sector Sociedades", layout="wide")

st.title("🤖 Sistema de Automatización Contable")
st.subheader("Asociaciones Civiles - Motor de Importación Directa para 'ONVIO'")

# 1. CUENTAS CONTABLES FIJAS
CUENTA_BANCO_COMAFI = "11016010"  # CTA/CTE $ COMAFI 1070-01085-6
CUENTA_PUENTE_DEF = "13000000"

# 2. MAPEO DE EQUIVALENCIAS CONTABLES
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
    
    fecha_en_memoria = None
    concepto_acumulado = ""
    freno_activado = False
    
    for linea in lineas:
        # DETECTAR FIN DEL EXTRACTO REAL PARA ACTIVAR EL FRENO DE MANO
        linea_upper = linea.upper()
        if "SALDO AL:" in linea_upper or "IMPUESTOS DEBITADOS" in linea_upper or "BASE IMPONIBLE" in linea_upper:
            freno_activado = True
            
        if freno_activado:
            continue # Ignora por completo cualquier línea posterior al saldo final del período
            
        partes = linea.split()
        if len(partes) == 0:
            continue
            
        # Comprobar si la línea arranca con una fecha válida (DD/MM/YY)
        tiene_fecha = re.match(r'^\d{2}/\d{2}/\d{2}$', partes[0])
        
        if tiene_fecha:
            fecha_en_memoria = partes[0]
            if "Saldo Anterior" in linea or "Transporte" in linea:
                continue
            concepto_acumulado = " ".join([x for x in partes[1:] if not re.match(r'^\d{6,12}$', x) and "," not in x])
        else:
            if not fecha_en_memoria:
                continue
            texto_secundario = " ".join([x for x in partes if not re.match(r'^\d{6,12}$', x) and "," not in x])
            if texto_secundario:
                concepto_acumulado += " " + texto_secundario

        # Buscar importes contables con coma decimal en la línea actual
        importes_validos = []
        for token in partes:
            if re.match(r'^\d{6,12}$', token): # Ignorar números de referencia largos
                continue
            token_clean = token.replace(".", "").replace(",", ".")
            if token_clean.endswith("-"):
                token_clean = "-" + token_clean[:-1]
            try:
                if "," in token: # Solo procesar formatos con decimales explícitos
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
            
        desc_final = concepto_acumulado.strip()
        
        # Determinar si es crédito
        es_credito = False
        desc_upper = desc_final.upper()
        if any(kw in desc_upper for kw in ["RECIBIDA", "CREDITOS", "DEPOSITO", "ACREDITADO", "RECIBID", "TONELLI", "CPS"]):
            es_credito = True
            
        movimientos.append({
            "Fecha": fecha_en_memoria,
            "Descripción": desc_final,
            "Importe": abs(importe_real),
            "EsCredito": es_credito
        })
        
        concepto_acumulado = ""
        
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
        st.success(f"Se extrajeron correctamente {len(df_origen)} transacciones respetando el límite final del extracto.")
        
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
                nombre_cuenta = "CUENTA PUENTE"
                
                for clave, datos in EQUIVALENCIAS_BASE.items():
                    if clave in desc_upper:
                        codigo_cuenta = datos[0]
                        nombre_cuenta = datos[1]
                        break
                
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
                    "Código de cuenta": str(codigo_cuenta),
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
                    "Código de cuenta": str(CUENTA_BANCO_COMAFI),
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
