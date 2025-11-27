# Guía de Integración Avanzada: ERPL + DuckDB para SAP RFC

Este documento detalla los hallazgos técnicos críticos, las mejores prácticas y la arquitectura implementada para la extracción de datos SAP utilizando la extensión ERPL para DuckDB (`sap_read_table`).

## 1. Arquitectura de Filtrado (Pushdown vs Local)

Para garantizar un rendimiento óptimo y evitar la transferencia excesiva de datos, es crucial entender dónde se ejecutan los filtros.

### El Problema del Filtrado SQL Estándar
DuckDB intenta optimizar las consultas aplicando filtros (`WHERE`) lo antes posible. Sin embargo:
*   **DuckDB** espera tipos SQL estándar (ej. `DATE` '2025-11-23').
*   **SAP (RFC_READ_TABLE)** espera tipos ABAP internos (ej. `DATS` '20251123').
*   La traducción automática de ERPL a veces falla, provocando errores como `SAPSQL_DATA_LOSS` (SAP rechaza el formato) o `Conversion Error` (DuckDB rechaza el formato SAP).

### La Solución: Pushdown Explícito (OpenSQL)
Hemos implementado una estrategia de **"Pass-Through"** donde los filtros se construyen en Python y se inyectan directamente en el parámetro `FILTER` de la función SAP, saltándose el motor SQL de DuckDB.

**Sintaxis de Llamada Optimizada:**
```sql
-- DuckDB SQL generado por el script
SELECT * FROM sap_read_table(
    'DFKKKO',           -- Tabla (Arg 1)
    MAX_ROWS=10,        -- Límite en origen (Arg 2)
    FILTER='CPUDT EQ ''20251123'' AND OPBEL EQ ''...''' -- Filtro OpenSQL (Arg 3)
)
```

## 2. Capacidades del Script de Extracción

El script `erpl_sapreadtable_export.py` ha sido robustecido con las siguientes capacidades:

### A. Soporte de Operadores OpenSQL
El script parsea los argumentos `--filter` y los traduce a sintaxis OpenSQL compatible:

| Operador CLI | Traducido a (OpenSQL) | Uso Recomendado | Nivel de Riesgo |
| :--- | :--- | :--- | :--- |
| `campo=valor` | `campo EQ 'valor'` | **Ideal**. Claves, Fechas, IDs. | 🟢 Bajo |
| `campo!=valor`| `campo NE 'valor'` | Exclusiones. | 🟡 Medio (Dep. Sistema) |
| `campo>valor` | `campo GT 'valor'` | Rangos, "No vacío". | 🟡 Medio |
| `campo>=valor`| `campo GE 'valor'` | Rangos de fecha/ID. | 🟡 Medio |
| `campo<valor` | `campo LT 'valor'` | Rangos. | 🟡 Medio |
| `campo<=valor`| `campo LE 'valor'` | Rangos. | 🟡 Medio |

*Nota: Aunque el script soporte la traducción, el sistema SAP destino (ej. R/3 antiguo) puede tener limitaciones en `RFC_READ_TABLE` que rechacen ciertos operadores (`OPTION_NOT_VALID`). En caso de duda, usar solo `EQ`.*

### B. Manejo de Tipos y Binding
Para evitar errores de "Binder Error" en DuckDB:
1.  Se utilizan **argumentos nombrados** (`MAX_ROWS=...`, `FILTER=...`) siempre que es posible.
2.  Se realizan **casteos explícitos** cuando se pasan argumentos posicionales o nulos (`CAST(NULL AS VARCHAR[])`).

## 3. Estrategia de Extracción Recomendada

Para entornos productivos (especialmente SAP R/3 Legacy):

1.  **Fase 1: Extracción Acotada (Pushdown)**
    *   Utilizar el script para extraer datos filtrando **solo por campos seguros**:
        *   Fechas (`--process-day` / `CPUDT=...`).
        *   IDs Clave (`OPBEL=...`).
        *   Límites (`--limit`).
    *   Esto minimiza la carga en la red y en SAP.

2.  **Fase 2: Refinamiento (Post-Processing)**
    *   Realizar filtros complejos (`!=`, `LIKE`, lógica de negocio) sobre el archivo CSV resultante o cargándolo en una tabla temporal de DuckDB.
    *   Esto evita errores `RFC_ABAP_EXCEPTION` y sobrecarga en el parser de SAP.

## 4. Instalación y Configuración

### Instalación de la Extensión
Usar siempre `INSTALL ... FROM ...` con sintaxis SQL estándar. Si hay bloqueos, verificar conectividad a `http://get.erpl.io`.

```python
# Script Python
con.sql(f"INSTALL '{ext_name}' FROM '{repo_url}';")
con.sql(f"LOAD '{ext_name}';")
```

### Parámetros de Conexión
DuckDB requiere variables de sesión. El script maneja esto automáticamente:
```sql
SET sap_ashost = '...';
SET sap_sysnr = '00';
-- etc.
```