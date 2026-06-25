# SPOT ESSENCE — Supply Chain Intelligence Platform
## Guía de instalación y deploy en Railway

---

## PASO 1 — Crear App en Azure (15 minutos, gratis)

> Esto permite que Railway lea el Excel directamente desde tu OneDrive.

1. Ir a **https://portal.azure.com** → iniciar sesión con la cuenta de Spot Essence
2. Buscar **"App registrations"** → clic en **"New registration"**
3. Nombre: `spot-supply-chain` → clic en **Register**
4. Anotar el **Application (client) ID** y el **Directory (tenant) ID** que aparecen en la pantalla

### Crear credencial (Client Secret)
5. En el menú izquierdo → **Certificates & secrets** → **New client secret**
6. Descripción: `railway-prod` · Expires: `24 months`
7. Clic en **Add** → **Copiar el Value inmediatamente** (solo se muestra una vez)

### Dar permisos al archivo de OneDrive
8. En el menú → **API permissions** → **Add a permission**
9. Seleccionar **Microsoft Graph** → **Application permissions**
10. Buscar y agregar:
    - `Files.Read.All`
    - `User.Read.All`
11. Clic en **Grant admin consent** (botón azul)

---

## PASO 2 — Subir el proyecto a GitHub

```bash
cd "C:\Users\FranciscaLagos\OneDrive - Spot Essence\Escritorio\Claude Code\spot-oc-app"
git init
git add .
git commit -m "SPOT Supply Chain Intelligence - Initial release"
# Crear repo en github.com/spotessence y conectar:
git remote add origin https://github.com/TU_ORG/spot-oc-app.git
git push -u origin main
```

---

## PASO 3 — Deploy en Railway

1. Ir a **https://railway.app** → **New Project** → **Deploy from GitHub repo**
2. Seleccionar el repo `spot-oc-app`
3. Railway detecta automáticamente que es Python/Flask con el `Procfile`

### Variables de entorno en Railway
En el panel de Railway → tu proyecto → **Variables** → agregar:

| Variable                  | Valor                                    |
|---------------------------|------------------------------------------|
| `AZURE_TENANT_ID`         | (valor de paso 1, paso 4)                |
| `AZURE_CLIENT_ID`         | (valor de paso 1, paso 4)                |
| `AZURE_CLIENT_SECRET`     | (valor de paso 1, paso 7)                |
| `ONEDRIVE_USER_EMAIL`     | `francisca.lagos@spotessence.cl`         |
| `EXCEL_FILE_PATH`         | `LOGÍSTICA - Documentos/Seguimientos OCs.xlsx` |
| `REFRESH_INTERVAL_MINUTES`| `60`                                     |

4. Clic en **Deploy** → Railway construye e inicia la app
5. Ir a **Settings** → **Domains** → generar URL pública (ej: `spot-oc.railway.app`)

---

## PASO 4 — Probar localmente (opcional)

```bash
cd "C:\Users\FranciscaLagos\OneDrive - Spot Essence\Escritorio\Claude Code\spot-oc-app"

# Copiar y completar variables
copy .env.example .env
# Editar .env con los valores reales de Azure

# Instalar dependencias
pip install -r requirements.txt

# Iniciar
python app.py
# Abrir: http://localhost:5000
```

---

## Cómo funciona la actualización automática

```
Excel en OneDrive (se actualiza N veces/día)
         ↓ cada 60 minutos
Microsoft Graph API (lee el archivo)
         ↓
Flask + Pandas (procesa y calcula KPIs)
         ↓
Dashboard en Railway (accesible 24/7)
```

- El Excel **nunca necesita moverse** ni exportarse manualmente
- El dashboard **se actualiza solo** cada hora
- Botón **"↻ Actualizar ahora"** en el nav para forzar recarga inmediata
- Si el archivo está en uso, se muestra la última lectura válida

---

## Acceso al dashboard

Una vez desplegado en Railway, la URL pública funciona desde:
- PC de escritorio (cualquier navegador)
- Laptop en reuniones
- TV para presentaciones S&OP (modo TV: zoom del navegador al 125%)
- Tablet / celular (diseño responsive)

---

## Estructura del proyecto

```
spot-oc-app/
├── app.py              ← Servidor Flask principal
├── config.py           ← Configuración y constantes
├── graph_client.py     ← Conexión a Microsoft Graph API (OneDrive)
├── data_loader.py      ← Lectura y transformación del Excel
├── kpi_calculator.py   ← Cálculo de KPIs y semáforos
├── requirements.txt    ← Dependencias Python
├── Procfile            ← Comando inicio Railway
├── railway.toml        ← Config Railway
├── .env.example        ← Plantilla variables de entorno
├── static/
│   ├── css/spot.css    ← Estilos corporativos SPOT
│   ├── js/dashboard.js ← Lógica frontend
│   └── img/logo.png    ← Logo SPOT ESSENCE
└── templates/
    └── dashboard.html  ← Template principal
```
