"""
Microsoft Graph API client.
Lee el archivo Excel desde SharePoint o OneDrive del usuario.
"""
import logging
import requests
import msal
from config import Config

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE      = ["https://graph.microsoft.com/.default"]


def _get_token() -> str:
    """Obtiene token de acceso usando Client Credentials Flow."""
    authority = f"https://login.microsoftonline.com/{Config.TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        Config.CLIENT_ID,
        authority=authority,
        client_credential=Config.CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        err = result.get("error_description", result.get("error", "unknown"))
        raise RuntimeError(f"No se pudo obtener token de Azure AD: {err}")
    return result["access_token"]


def download_excel_bytes() -> bytes:
    """
    Descarga el archivo Excel.
    Orden de intento:
      1. SharePoint site (SHAREPOINT_SITE env var)
      2. OneDrive personal del usuario
    """
    token = _get_token()

    # 1 — SharePoint site
    if Config.SHAREPOINT_SITE:
        try:
            return _download_from_sharepoint_site(token)
        except Exception as e:
            log.warning(f"SharePoint site falló ({e}), intentando OneDrive...")

    # 2 — OneDrive personal
    return _download_from_onedrive(token)


def _download_from_sharepoint_site(token: str) -> bytes:
    """
    Descarga el archivo desde un SharePoint site.
    Recorre las drives del site hasta encontrar el archivo.
    """
    headers = {"Authorization": f"Bearer {token}"}
    site_ref = Config.SHAREPOINT_SITE  # e.g. "spotessence1.sharepoint.com:/sites/LOGSTICA"

    # Obtener site ID
    site_url = f"{GRAPH_BASE}/sites/{site_ref}"
    site_resp = requests.get(site_url, headers=headers, timeout=30)
    site_resp.raise_for_status()
    site_id = site_resp.json()["id"]
    log.info(f"SharePoint site ID: {site_id}")

    # Listar drives del site
    drives_resp = requests.get(f"{GRAPH_BASE}/sites/{site_id}/drives", headers=headers, timeout=30)
    drives_resp.raise_for_status()
    drives = drives_resp.json().get("value", [])
    log.info(f"Drives encontrados en el site: {[d['name'] for d in drives]}")

    file_name = Config.EXCEL_FILE_PATH.split("/")[-1]

    for drive in drives:
        drive_id   = drive["id"]
        drive_name = drive.get("name", "")
        encoded    = requests.utils.quote(Config.EXCEL_FILE_PATH, safe="/")
        url        = f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}:/content"
        resp       = requests.get(url, headers=headers, timeout=60)
        if resp.status_code == 200:
            log.info(f"Excel descargado desde drive '{drive_name}' ({len(resp.content):,} bytes)")
            return resp.content
        # También buscar solo por nombre en la raíz del drive
        url2  = f"{GRAPH_BASE}/drives/{drive_id}/root:/{file_name}:/content"
        resp2 = requests.get(url2, headers=headers, timeout=60)
        if resp2.status_code == 200:
            log.info(f"Excel encontrado en raíz de drive '{drive_name}' ({len(resp2.content):,} bytes)")
            return resp2.content

    # Búsqueda por nombre como último recurso
    log.info(f"Buscando '{file_name}' en el site via search...")
    search_url  = f"{GRAPH_BASE}/sites/{site_id}/drive/search(q='{file_name}')"
    search_resp = requests.get(search_url, headers=headers, timeout=30)
    if search_resp.status_code == 200:
        items = search_resp.json().get("value", [])
        for item in items:
            if item.get("name", "").lower() == file_name.lower():
                dl_url = item.get("@microsoft.graph.downloadUrl") or item.get("webUrl")
                if "@microsoft.graph.downloadUrl" in item:
                    file_resp = requests.get(item["@microsoft.graph.downloadUrl"], timeout=60)
                    if file_resp.status_code == 200:
                        log.info(f"Excel encontrado via search ({len(file_resp.content):,} bytes)")
                        return file_resp.content

    raise FileNotFoundError(
        f"No se encontró '{Config.EXCEL_FILE_PATH}' en el SharePoint site '{Config.SHAREPOINT_SITE}'"
    )


def _download_from_onedrive(token: str) -> bytes:
    """Descarga desde el OneDrive personal del usuario."""
    headers   = {"Authorization": f"Bearer {token}"}
    file_path = Config.EXCEL_FILE_PATH.replace("\\", "/").lstrip("/")
    encoded   = requests.utils.quote(file_path, safe="/")

    url  = f"{GRAPH_BASE}/users/{Config.USER_EMAIL}/drive/root:/{encoded}:/content"
    log.info(f"Descargando Excel desde OneDrive: {url}")
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code == 200:
        log.info(f"Excel descargado OK — {len(resp.content):,} bytes")
        return resp.content

    # Intentar drives del usuario
    drives_resp = requests.get(f"{GRAPH_BASE}/users/{Config.USER_EMAIL}/drives", headers=headers, timeout=30)
    drives_resp.raise_for_status()
    for drive in drives_resp.json().get("value", []):
        drive_id = drive["id"]
        r = requests.get(f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}:/content",
                         headers=headers, timeout=60)
        if r.status_code == 200:
            log.info(f"Excel encontrado en drive {drive_id}")
            return r.content

    resp.raise_for_status()


def _encode_share_url(share_url: str) -> str:
    """Codifica una URL para usarla como shareId en /shares/{id}."""
    import base64
    b64 = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("utf-8")
    b64 = b64.rstrip("=")
    return "u!" + b64


def get_latest_file_in_folder(share_url: str, name_contains: str = "") -> dict:
    """
    Resuelve un link de carpeta compartida de SharePoint y retorna el
    metadata del archivo .xlsx más reciente (por lastModifiedDateTime).
    """
    token   = _get_token()
    headers = {"Authorization": f"Bearer {token}"}
    share_id = _encode_share_url(share_url)

    url  = f"{GRAPH_BASE}/shares/{share_id}/driveItem/children"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("value", [])

    xlsx = [it for it in items if it.get("name", "").lower().endswith(".xlsx")]
    if name_contains:
        filtered = [it for it in xlsx if name_contains.lower() in it["name"].lower()]
        xlsx = filtered or xlsx

    if not xlsx:
        raise FileNotFoundError("No se encontraron archivos .xlsx en la carpeta de SharePoint")

    xlsx.sort(key=lambda it: it.get("lastModifiedDateTime", ""), reverse=True)
    latest = xlsx[0]
    log.info(f"Archivo más reciente en carpeta: {latest['name']} ({latest.get('lastModifiedDateTime')})")
    return latest


def download_file_content(item: dict) -> bytes:
    """Descarga el contenido binario de un driveItem (dict retornado por Graph)."""
    download_url = item.get("@microsoft.graph.downloadUrl")
    if download_url:
        resp = requests.get(download_url, timeout=60)
        resp.raise_for_status()
        return resp.content

    token    = _get_token()
    headers  = {"Authorization": f"Bearer {token}"}
    drive_id = item["parentReference"]["driveId"]
    item_id  = item["id"]
    url      = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.content


def download_latest_from_folder(share_url: str, name_contains: str = "") -> tuple[bytes, str, str | None]:
    """
    Descarga el archivo .xlsx más reciente de una carpeta compartida de SharePoint.
    Retorna (bytes, nombre_archivo, lastModifiedDateTime).
    """
    item = get_latest_file_in_folder(share_url, name_contains)
    content = download_file_content(item)
    return content, item["name"], item.get("lastModifiedDateTime")


def get_file_last_modified() -> str | None:
    """Retorna la fecha de última modificación del Excel."""
    try:
        token   = _get_token()
        headers = {"Authorization": f"Bearer {token}"}

        if Config.SHAREPOINT_SITE:
            site_url  = f"{GRAPH_BASE}/sites/{Config.SHAREPOINT_SITE}"
            site_resp = requests.get(site_url, headers=headers, timeout=30)
            if site_resp.status_code == 200:
                site_id = site_resp.json()["id"]
                encoded = requests.utils.quote(Config.EXCEL_FILE_PATH, safe="/")
                url = f"{GRAPH_BASE}/sites/{site_id}/drive/root:/{encoded}"
                resp = requests.get(url, headers=headers, timeout=30)
                if resp.status_code == 200:
                    return resp.json().get("lastModifiedDateTime")

        file_path = Config.EXCEL_FILE_PATH.replace("\\", "/").lstrip("/")
        encoded   = requests.utils.quote(file_path, safe="/")
        url  = f"{GRAPH_BASE}/users/{Config.USER_EMAIL}/drive/root:/{encoded}"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("lastModifiedDateTime")
    except Exception as e:
        log.warning(f"No se pudo obtener lastModified: {e}")
    return None
