"""
fa_calculator.py — SPOT ESSENCE Forecast Accuracy
Centraliza TODA la lógica de cálculo de FA.
Para cambiar la fórmula, modifica ÚNICAMENTE las funciones de este módulo.
"""
import pandas as pd


# ══════════════════════════════════════════════════════════════════════════════
#  FÓRMULA BASE — modifica aquí para cambiar el cálculo
# ══════════════════════════════════════════════════════════════════════════════

def compute_fa(forecast: float, venta_real: float) -> float:
    """
    Forecast Accuracy para un par (forecast, venta_real).

    Fórmula actual:
        FA = max(0, 1 - |Venta - Forecast| / Forecast) × 100

    Reglas de borde:
        Forecast = 0, Venta = 0  →  100 %  (predicción perfecta vacía)
        Forecast = 0, Venta > 0  →    0 %  (se perdió toda la venta)

    Retorna porcentaje (0.0 – 100.0), redondeado a 1 decimal.
    """
    f = float(forecast  or 0)
    v = float(venta_real or 0)
    if f <= 0:
        return 100.0 if v == 0 else 0.0
    return round(max(0.0, (1.0 - abs(v - f) / f) * 100.0), 1)


# ══════════════════════════════════════════════════════════════════════════════
#  AGREGACIÓN PONDERADA (KPIs globales y por grupo)
# ══════════════════════════════════════════════════════════════════════════════

def compute_fa_weighted(total_forecast: float, total_error: float) -> float:
    """
    FA ponderada por volumen: 1 - ΣError / ΣForecast
    Más estable que promediar FA individuales cuando los volúmenes difieren.

    Usar para: KPI global, FA por cliente, FA por mes.
    """
    if total_forecast <= 0:
        return 100.0 if total_error == 0 else 0.0
    return round(max(0.0, (1.0 - total_error / total_forecast) * 100.0), 1)


def fa_from_df(df: pd.DataFrame, col_forecast: str, col_venta: str) -> float:
    """FA ponderada a partir de un DataFrame (suma de error / suma de forecast)."""
    tf = float(df[col_forecast].sum())
    te = float((df[col_venta] - df[col_forecast]).abs().sum())
    return compute_fa_weighted(tf, te)


# ══════════════════════════════════════════════════════════════════════════════
#  VERSIÓN VECTORIZADA (aplica compute_fa fila a fila)
# ══════════════════════════════════════════════════════════════════════════════

def compute_fa_series(df: pd.DataFrame, col_forecast: str, col_venta: str) -> pd.Series:
    """Aplica compute_fa() elemento a elemento. Úsala para columna FA en tablas detalle."""
    return df.apply(
        lambda r: compute_fa(r[col_forecast], r[col_venta]),
        axis=1,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  SEMÁFORO DE COLORES
# ══════════════════════════════════════════════════════════════════════════════

def fa_chip_class(fa: float) -> str:
    """Clase CSS para chip de color (reutiliza paleta SPOT)."""
    if fa >= 80: return "c-green"
    if fa >= 60: return "c-yellow"
    if fa >= 40: return "c-orange"
    return "c-red"


def fa_semaforo(fa: float) -> str:
    if fa >= 80: return "green"
    if fa >= 60: return "yellow"
    if fa >= 40: return "orange"
    return "red"


def fa_heatmap_color(fa: float) -> str:
    """Color de fondo para celda de heatmap."""
    if fa >= 80: return "#dcfce7"
    if fa >= 60: return "#fef9c3"
    if fa >= 40: return "#ffedd5"
    return "#fee2e2"
