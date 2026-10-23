def procesar_lineas_comafi(text):
    movimientos = []
    lineas = text.split("\n")
    
    fecha_en_memoria = None
    concepto_acumulado = ""
    freno_activado = False
    en_corte_de_hoja = False  # entre el "Transporte" de una hoja y el primer importe de la siguiente
    movimiento_pendiente = False  # fecha + descripción sin importe, esperando el monto en la línea/hoja siguiente
    
    for linea in lineas:
        linea_upper = linea.upper()
        partes = linea.split()
        if len(partes) == 0:
            continue
        
        # Salto de hoja: igual que antes, cada hoja arranca de cero...
        if linea.strip() == MARCA_SALTO_HOJA:
            freno_activado = False
            en_corte_de_hoja = True
            # ...SALVO que haya quedado un movimiento cortado (fecha al pie, importe en la hoja siguiente)
            if not movimiento_pendiente:
                fecha_en_memoria = None
                concepto_acumulado = ""
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

        importes_validos = []
        for token in partes:
            if not es_importe(token):
                continue
            token_clean = token.replace(".", "").replace(",", ".")
            if token_clean.endswith("-"):
                token_clean = "-" + token_clean[:-1]
            importes_validos.append(float(token_clean))

        if not importes_validos:
            continue  
        
        en_corte_de_hoja = False
            
        if len(importes_validos) >= 2:
            importe_real = importes_validos[-2]
        else:
            importe_real = importes_validos[-1]
            
        desc_final = concepto_acumulado.strip()
        
        desc_upper = desc_final.upper()
        es_credito = (any(kw in desc_upper for kw in CLAVES_CREDITO)
                      and not any(kw in desc_upper for kw in CLAVES_DEBITO_FORZADO))
            
        movimientos.append({
            "Fecha": str(fecha_en_memoria), # Forzado a texto plano
            "Descripción": desc_final,
            "Importe": abs(importe_real),
            "EsCredito": es_credito
        })
        concepto_acumulado = ""
        movimiento_pendiente = False
        
    return movimientos
