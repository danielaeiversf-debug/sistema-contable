import streamlit as st
import pandas as pd
import pdfplumber
import io

st.set_page_config(page_title="Automatizador Contable - Sector Sociedades", layout="wide")

st.title("🤖 Sistema de Automatización Contable")
st.subheader("Asociaciones Civiles - Motor de Importación Directa para 'Obvio'")

# 1. CUENTAS CONTABLES FIJAS (Extraídas de tu Plan de Cuentas)
CUENTA_BANCO_COMAFI = "11016010"  # CTA/CTE $ COMAFI 1070-01085-6

# 2. DICCIONARIO INTELIGENTE AMPLIADO (Cuentas de Pérdidas y Gastos Bancarios Exactas)
EQUIVALENCIAS_BASE = {
    "DEB LEY 25413": ("53070000", "IMPUESTO DEB LEY 25413"),
    "CRED LEY 25413": ("53080000", "IMPUESTO CRED LEY 25413"),
    "IMP.LEY 25413 DEB": ("53070000", "IMPUESTO DEB LEY 25413"),
    "IMP.LEY 25413 CRE": ("53080000", "IMPUESTO CRED LEY 25413"),
    "GASTOS BANCARIOS": ("53010000", "GASTOS BANCARIOS"),
    "COMISION": ("53010000", "GASTOS BANCARIOS"),
    "INTERESES PAGADOS": ("53020000", "RECARGOS E INTERESES PAGAD."),
    "INTERES BANCARIO": ("53030000", "INTERESES BANCARIOS"),
    "SUELDOS Y JORNALES": ("21013010", "SUELDOS Y JORNALES A PAGAR"),
    "PROV": ("21012010", "PROVEEDORES"),
    "HONORARIOS": ("52020000", "HONORARIOS PROFESIONALES"),
    "AFIP IVA": ("21014030", "DGI IVA A PAGAR"),
    "LUZ": ("52100000", "LUZ"),
    "GAS NATURAL": ("51330000", "GAS NATURAL"),
    "GAS": ("52150000", "GAS"),
    "TELEFONO": ("52180000", "TELEFONO"),
    "DONACION": ("43020000", "DONACIONES"),
    "SUBSIDIO": ("42070000", "SUBSIDIOS")
}

# Configuración en la barra lateral
st.sidebar.header("⚙️ Parámetros de Importación")
nro_asiento_inicial = st.sidebar.number_input("Número de Asiento Inicial", min_value=1, value=1, step=1)
cuenta_puente = st.sidebar.text_input("Cuenta Puente (Sin coincidencia)", value="13000000") # Tu Cuenta Puente real

# Interfaz de carga
st.markdown("### 1. Cargar Extracto Bancario Obligatorio")
archivo_cargado = st.file_uploader("Arrastrá el PDF nativo del Home Banking, Excel o CSV", type=["pdf", "xlsx", "xls", "csv"])

def procesar_pdf_bancario(file_bytes):
    movimientos = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for linea in text.split("\n"):
                    partes = linea.split()
                    if len(partes) >= 3:
                        fecha = partes[0]
                        if "/" in fecha or "-" in fecha:
                            try:
                                imp_str = partes[-1].replace(".", "").replace(",", ".")
                                importe = float(imp_str)
                                descripcion = " ".join(partes[1:-1])
                                movimientos.append({"Fecha": fecha, "Descripción": descripcion, "Importe": importe})
                            except ValueError:
                                continue
    return pd.DataFrame(movimientos)

if archivo_cargado is not None:
    st.success("Archivo recibido de forma exitosa.")
    
    ext = archivo_cargado.name.split(".")[-1].lower()
    df_origen = pd.DataFrame()
    
    if ext == "pdf":
        df_origen = procesar_pdf_bancario(archivo_cargado.read())
    elif ext in ["xlsx", "xls"]:
        df_origen = pd.read_excel(archivo_cargado)
    elif ext == "csv":
        df_origen = pd.read_csv(archivo_cargado)
        
    if not df_origen.empty:
        st.markdown("### 2. Control de Columnas y Mapeo Automático")
        
        columnas = df_origen.columns.tolist()
        col_fecha = st.selectbox("Columna de Fecha", columnas, index=0)
        col_desc = st.selectbox("Columna de Descripción / Detalle", columnas, index=1 if len(columnas)>1 else 0)
        col_imp = st.selectbox("Columna de Importe", columnas, index=2 if len(columnas)>2 else 0)
        
        asientos_obvio = []
        asiento_actual = nro_asiento_inicial
        
        for idx, fila in df_origen.iterrows():
            try:
                fecha = str(fila[col_fecha])
                desc = str(fila[col_desc])
                val_imp = str(fila[col_imp]).replace(".", "").replace(",", ".")
                importe = float(val_imp)
            except:
                continue
                
            desc_upper = desc.upper()
            codigo_cuenta = cuenta_puente
            nombre_cuenta = "REVISAR - IMPUTADO A CUENTA PUENTE"
            
            for clave, datos in EQUIVALENCIAS_BASE.items():
                if clave in desc_upper:
                    codigo_cuenta = datos[0]
                    nombre_cuenta = datos[1]
                    break
            
            # DETERMINACIÓN DE SIGNOS Y SENTIDO DEL ASIENTO
            # En Obvio, para mantener consistencia de signos:
            # Si el importe es un egreso (Débito en cuenta), impacta positivo en Gasto y negativo en Banco.
            # Si el importe es un ingreso (Crédito en cuenta), se invierte el sentido para balancear.
            
            # Pase 1: Cuenta Destino Imputada
            asientos_obvio.append({
                "Número de asiento": asiento_actual,
                "Número de Pase": 1,
                "Fecha": fecha,
                "Concepto": "Asiento Resumen Bancario",
                "Código de cuenta": codigo_cuenta,
                "Importe en moneda local": importe,
                "Importe en moneda ext.present.": 0.0,
                "Leyenda": f"{nombre_cuenta} - {desc}",
                "Código de centro de costos": "",
                "Porcentaje de distribución": "",
                "Imp.mon.local dist.C.Costos": "",
                "Imp.mon.present.dist.C.Costos": ""
            })
            
            # Pase 2: Contrapartida Balanceada de Banco Comafi
            asientos_obvio.append({
                "Número de asiento": asiento_actual,
                "Número de Pase": 2,
                "Fecha": fecha,
                "Concepto": "Asiento Resumen Bancario",
                "Código de cuenta": CUENTA_BANCO_COMAFI,
                "Importe en moneda local": -importe,
                "Importe en moneda ext.present.": 0.0,
                "Leyenda": f"COMAFI CTA CTE - {desc}",
                "Código de centro de costos": "",
                "Porcentaje de distribución": "",
                "Imp.mon.local dist.C.Costos": "",
                "Imp.mon.present.dist.C.Costos": ""
            })
            
            asiento_actual += 1
            
        df_resultado = pd.DataFrame(asientos_obvio)
        
        if not df_resultado.empty:
            st.write("#### Previsualización de los Asientos a Exportar:")
            st.dataframe(df_resultado)
            
            suma_total = df_resultado["Importe en moneda local"].sum()
            if abs(suma_total) < 0.01:
                st.success("✅ Validación Exitosa: El Debe y el Haber cierran en cero perfectamente.")
            else:
                st.warning(f"⚠️ Alerta de descuadre: La suma de los movimientos da {suma_total}. Revisar signos.")
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_resultado.to_excel(writer, index=False, sheet_name='Importacion_Obvio')
            excel_data = output.getvalue()
            
            st.markdown("### 3. Exportación Final")
            st.download_button(
                label="📥 Descargar Archivo para Subir a Obvio",
                data=excel_data,
                file_name="asientos_listos_obvio.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("No se detectaron movimientos contables válidos en el archivo.")
