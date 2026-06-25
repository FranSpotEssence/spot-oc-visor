import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Azure AD
    TENANT_ID     = os.getenv("AZURE_TENANT_ID", "")
    CLIENT_ID     = os.getenv("AZURE_CLIENT_ID", "")
    CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")

    # OneDrive / SharePoint
    USER_EMAIL       = os.getenv("ONEDRIVE_USER_EMAIL", "francisca.lagos@spotessence.cl")
    SHAREPOINT_SITE  = os.getenv("SHAREPOINT_SITE", "")   # e.g. "tenant.sharepoint.com:/sites/SITE"
    EXCEL_FILE_PATH  = os.getenv("EXCEL_FILE_PATH", "Seguimientos OCs.xlsx")

    # App
    REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL_MINUTES", "60"))
    SECRET_KEY       = os.getenv("SECRET_KEY", "spot-essence-secret-2024")
    APP_PASSWORD     = ""  # Sin contraseña — acceso directo

    # Semaphore thresholds
    FR_GREEN  = 95.0   # >= 95%  → verde
    FR_YELLOW = 90.0   # 90-94.9% → amarillo
    FR_ORANGE = 80.0   # 80-89.9% → naranjo  |  < 80% → rojo

    OC_RISK_GREEN  = 0
    OC_RISK_YELLOW = 5
    OC_RISK_ORANGE = 10

    DAYS_ALERT_UPCOMING = 3

    # Sheet & header config
    SHEET_NAME = "Registro OC"
    HEADER_ROW = 1   # pandas 0-indexed → fila 2 del Excel

    # Column name map (nombre exacto en Excel → alias interno)
    COL_MAP = {
        "CLIENTE":             "cliente",
        "OC":                  "oc",
        "ESTADO OC":           "estado",
        "FECHA EMISIÓN":       "fecha_emision",
        "FECHA DESPACHO":      "fecha_despacho",
        "EAN CLIENTE":         "ean_cliente",
        "EAN SPOT":            "ean_spot",
        "PRODUCTO":            "producto",
        "CATEGORIA":           "categoria",
        "MARCA":               "marca",
        "UM":                  "um",
        "UN SOLICITADAS":      "un_solicitadas",
        "PRECIO NETO UN OC":   "precio_oc",
        "PRECIO NETO UNI LP":  "precio_lp",
        "DIFERENCIA DE PRECIO":"diff_precio",
        "VALOR TOTAL":         "valor_total",
        "UNIDADES ASIGNADAS":  "un_asignadas",
        "VALOR FACTURADO":     "valor_facturado",
        "BO UN":               "bo_un",
        "BO VALORIZADO":       "bo_valorizado",
        "COMENTARIOS":         "comentarios",
        "MOTIVO BO":                    "motivo_bo",
        "CATEGORÍA ARBOL DE PÉRDIDA":   "categoria_arbol",
        "STOCK":               "stock",
        "Correlativo SKU":     "correlativo_sku",
    }
