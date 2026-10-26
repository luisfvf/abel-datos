import csv
import io
import os
import html
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

# En Render se usa DATABASE_URL (la inyecta render.yaml); en local, las variables DB_*
DATABASE_URL = os.getenv("DATABASE_URL")
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "relevamiento_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "127.0.0.1"),  # IP del servidor Postgres, NO 0.0.0.0
    "port": int(os.getenv("DB_PORT", "5432")),
}


def conectar():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    return psycopg2.connect(**DB_CONFIG)


def crear_esquema(intentos=10):
    """Crea la tabla y la vista si no existen. Reintenta porque la BD puede tardar en estar lista."""
    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    for i in range(1, intentos + 1):
        try:
            with closing(conectar()) as conn, conn, conn.cursor() as cursor:
                cursor.execute(sql)
            print("Esquema verificado.")
            return
        except psycopg2.OperationalError as e:
            print(f"BD no disponible (intento {i}/{intentos}): {e}")
            time.sleep(3)
    raise RuntimeError("No se pudo conectar a la base de datos")


@asynccontextmanager
async def lifespan(app):
    crear_esquema()
    yield


app = FastAPI(lifespan=lifespan)

# Columnas de la tabla (el nombre en MAYÚSCULAS es la clave del JSON que envía PowerShell)
COLUMNAS = [
    "fecha", "juzgado", "edificio", "piso", "hostname", "service_tag",
    "nombre_usuario", "rol", "marca", "modelo", "procesador",
    "tipo_disco", "tamano_disco", "tipo_ram", "tamano_memoria",
    "cod_act_pc", "marca_impresora", "modelo_impresora", "conexion_impresora", "cod_act_imp",
    "tipo_equipo", "fecha_bios", "version_bios", "so_nombre", "so_build",
    "fecha_instalacion_so", "cpu_nucleos", "cpu_hilos", "cpu_mhz",
    "ram_slots_usados", "ram_slots_total", "ram_mhz",
    "disco_salud", "disco_smart", "disco_desgaste_pct", "disco_horas_uso", "disco_libre_gb",
    "tpm_version", "secure_boot", "ip", "mac", "dominio",
]


def esc(valor):
    """Escapa HTML y evita mostrar 'None'."""
    return html.escape(str(valor)) if valor is not None else ""


# --- 1. RUTA PARA EL NAVEGADOR ---
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    base_url = str(request.base_url).rstrip("/")
    # TLS 1.2 forzado: PowerShell 5.1 en equipos viejos no lo usa por defecto y falla con HTTPS
    comando_powershell = esc(
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
        f"iex (New-Object Net.WebClient).DownloadString('{base_url}/script')"
    )

    return f"""
    <html>
        <head>
            <title>Servidor de Relevamiento</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background-color: #f4f6f9; color: #333; }}
                .container {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 700px; margin: auto; }}
                h1 {{ color: #2c3e50; }}
                code {{ background: #2d3748; color: #a3e635; padding: 15px; display: block; border-radius: 5px; font-size: 16px; overflow-x: auto; word-break: break-all; }}
                .pasos {{ font-weight: bold; margin-top: 20px; color: #4a5568; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Relevamiento de Equipos</h1>
                <p>Para escanear este equipo sin usar memorias Flash o pendrives, sigue estos pasos:</p>
                <p class="pasos">Paso 1: Abre PowerShell <u>como Administrador</u> (necesario para leer estado del disco, TPM y Secure Boot).</p>
                <p class="pasos">Paso 2: Copia y pega el siguiente comando exacto y presiona Enter:</p>
                <code>{comando_powershell}</code>
                <p style="margin-top:20px; font-size: 12px; color: #718096;">El comando descargará temporalmente el script en memoria, extraerá el hardware y guardará todo en PostgreSQL.</p>
                <p style="margin-top:20px;"><a href="/visor">Ver equipos registrados →</a></p>
            </div>
        </body>
    </html>
    """


# --- 2. RUTA QUE ENTREGA EL CODIGO POWERSHELL "EN CALIENTE" ---
# Constante con placeholder: así NO hace falta duplicar las llaves { } de PowerShell.
SCRIPT_PS = r"""
Clear-Host
Write-Host "--- INICIANDO DIAGNOSTICO EN MEMORIA VOLATIL ---" -ForegroundColor Yellow

# ---------- Compatibilidad: se necesita PowerShell 3.0 o superior ----------
if ($PSVersionTable.PSVersion.Major -lt 3) {
    Write-Host "[ERROR] Este equipo tiene PowerShell $($PSVersionTable.PSVersion) (Windows XP/Vista/7 sin actualizar)." -ForegroundColor Red
    Write-Host "Instale WMF 5.1 o registre este equipo manualmente." -ForegroundColor Red
    Start-Sleep -Seconds 5
    return
}

function Nz($v, $d = "Desconocido") {
    if ($null -eq $v) { return $d }
    $s = ([string]$v).Trim()
    if ($s -eq "") { return $d }
    return $s
}

$EsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $EsAdmin) {
    Write-Host "[AVISO] No eres Administrador: se omitiran TPM, Secure Boot y desgaste del disco." -ForegroundColor Yellow
}

# ---------- Red (antes que el service tag, porque se usa como respaldo) ----------
$HostName = [System.Net.Dns]::GetHostName()
$Ip  = ""
$Mac = ""
$Net = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -and $_.IPAddress } | Select-Object -First 1
if ($Net) { $Ip = $Net.IPAddress[0]; $Mac = $Net.MACAddress }

# ---------- Identificacion ----------
$CS      = Get-CimInstance Win32_ComputerSystem
$Marca   = Nz $CS.Manufacturer
$Dominio = $CS.Domain
$Modelo  = Nz (Get-CimInstance Win32_ComputerSystemProduct).Name

$Bios        = Get-CimInstance Win32_BIOS
$VersionBios = Nz $Bios.SMBIOSBIOSVersion ""
$FechaBios   = $null
if ($Bios.ReleaseDate) { $FechaBios = $Bios.ReleaseDate.ToString("yyyy-MM-dd") }

# Service tag: si es generico o vacio, se usa GEN-<MAC>
$ServiceTag = Nz $Bios.SerialNumber ""
$Genericos  = @("none","default string","to be filled by o.e.m.","system serial number","o.e.m.","n/a","not specified","unknown","serial number","not applicable","chassis serial number","base board serial number","123456789","1234567890")
$EsGenerico = ($ServiceTag.Length -lt 4) -or ($Genericos -contains $ServiceTag.ToLower()) -or ($ServiceTag -match '^(0+|f+|x+|-+|\.+)$')
if ($EsGenerico) {
    $Base = $Mac -replace '[:\-]', ''
    if (-not $Base) { $Base = $HostName }
    $ServiceTag = "GEN-" + $Base
    Write-Host "[AVISO] Service tag generico o vacio, se usara: $ServiceTag" -ForegroundColor Yellow
}

# Laptop o Desktop (ChassisTypes: 8,9,10,11,12,14,18,21,30,31,32 = portatiles)
$Chassis    = (Get-CimInstance Win32_SystemEnclosure).ChassisTypes
$TipoEquipo = "Desktop"
if (@($Chassis | Where-Object { @(8,9,10,11,12,14,18,21,30,31,32) -contains $_ }).Count -gt 0) { $TipoEquipo = "Laptop" }

# ---------- Sistema operativo ----------
$OS         = Get-CimInstance Win32_OperatingSystem
$SoNombre   = Nz $OS.Caption ""
$SoBuild    = Nz $OS.BuildNumber ""
$FechaInsSO = $null
if ($OS.InstallDate) { $FechaInsSO = $OS.InstallDate.ToString("yyyy-MM-dd") }

# ---------- CPU ----------
$Cpu        = Get-CimInstance Win32_Processor | Select-Object -First 1
$CpuInfo    = Nz $Cpu.Name
$CpuNucleos = $null
$CpuHilos   = $null
if ([int]$Cpu.NumberOfCores -gt 0)             { $CpuNucleos = [int]$Cpu.NumberOfCores }
if ([int]$Cpu.NumberOfLogicalProcessors -gt 0) { $CpuHilos   = [int]$Cpu.NumberOfLogicalProcessors }
$CpuMhz = [int]$Cpu.MaxClockSpeed

# ---------- RAM ----------
$Mem      = @(Get-CimInstance Win32_PhysicalMemory)
$RamBytes = ($Mem | Measure-Object Capacity -Sum).Sum
if ($RamBytes -lt 1GB) {
    $TextoRAM = "$([Math]::Round($RamBytes / 1MB)) MB"
} else {
    $TextoRAM = "$([Math]::Round($RamBytes / 1GB)) GB"
}
$RamSlotsUsados = $Mem.Count
$RamSlotsTotal  = (Get-CimInstance Win32_PhysicalMemoryArray | Measure-Object MemoryDevices -Sum).Sum
$M1             = $Mem | Select-Object -First 1
$RamMhz         = $M1.Speed

$TipoRAM = "Desconocido"
$Smb = [int]$M1.SMBIOSMemoryType
switch ($Smb) {
    15 { $TipoRAM = "SDRAM" }
    18 { $TipoRAM = "DDR" }
    19 { $TipoRAM = "DDR2" }
    24 { $TipoRAM = "DDR3" }
    26 { $TipoRAM = "DDR4" }
    27 { $TipoRAM = "LPDDR" }
    28 { $TipoRAM = "LPDDR2" }
    29 { $TipoRAM = "LPDDR3" }
    30 { $TipoRAM = "LPDDR4" }
    34 { $TipoRAM = "DDR5" }
    35 { $TipoRAM = "LPDDR5" }
}
if ($Smb -eq 0) {
    # Equipos viejos / Windows 7: propiedad antigua MemoryType
    switch ([int]$M1.MemoryType) {
        17 { $TipoRAM = "SDRAM" }
        20 { $TipoRAM = "DDR" }
        21 { $TipoRAM = "DDR2" }
        24 { $TipoRAM = "DDR3" }
    }
}

# ---------- Disco (el que contiene C:) ----------
$DiskNum = 0
try { $DiskNum = [int](Get-Partition -DriveLetter C -ErrorAction Stop).DiskNumber } catch { }

$DiskPhysical = Get-CimInstance Win32_DiskDrive | Where-Object { $_.Index -eq $DiskNum } | Select-Object -First 1
if ($null -eq $DiskPhysical) { $DiskPhysical = Get-CimInstance Win32_DiskDrive | Select-Object -First 1 }
$DiscoGB    = [Math]::Round($DiskPhysical.Size / 1GB)
$TextoDisco = "$DiscoGB GB"

$VolC         = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$DiscoLibreGB = $null
if ($VolC) { $DiscoLibreGB = [int][Math]::Round($VolC.FreeSpace / 1GB) }

$TipoDisco     = "Desconocido"
$DiscoSalud    = ""
$DiscoDesgaste = $null
$DiscoHoras    = $null

$PD = $null
if (Get-Command Get-PhysicalDisk -ErrorAction SilentlyContinue) {
    $PD = Get-PhysicalDisk -ErrorAction SilentlyContinue | Where-Object { [int]$_.DeviceID -eq $DiskNum } | Select-Object -First 1
}
if ($PD) {
    if     ($PD.MediaType -eq "SSD" -or $PD.BusType -eq "NVMe") { $TipoDisco = "SSD" }
    elseif ($PD.MediaType -eq "HDD") { $TipoDisco = "HDD" }
    $DiscoSalud = [string]$PD.HealthStatus
    if ($EsAdmin) {
        $Rel = $PD | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
        if ($Rel) {
            $DiscoDesgaste = $Rel.Wear
            $DiscoHoras    = $Rel.PowerOnHours
        }
    }
}
if ($TipoDisco -eq "Desconocido" -and $DiskPhysical.Model -match 'SSD|NVMe|Solid State') { $TipoDisco = "SSD" }

# Prediccion de falla SMART (solo Administrador)
$DiscoSmart = ""
if ($EsAdmin) {
    try {
        $Smart = Get-CimInstance -Namespace "root/wmi" -ClassName MSStorageDriver_FailurePredictStatus -ErrorAction Stop
        if (@($Smart | Where-Object { $_.PredictFailure }).Count -gt 0) { $DiscoSmart = "FALLA" } else { $DiscoSmart = "OK" }
    } catch { }
}

# ---------- Seguridad / Windows 11 ----------
$TpmVersion = ""
$SecureBoot = ""
if ($EsAdmin) {
    try {
        $Tpm = Get-CimInstance -Namespace "root/cimv2/Security/MicrosoftTpm" -ClassName Win32_Tpm -ErrorAction Stop
        if ($Tpm) { $TpmVersion = ($Tpm.SpecVersion -split ",")[0].Trim() } else { $TpmVersion = "SIN TPM" }
    } catch { $TpmVersion = "SIN TPM" }
    try {
        if (Confirm-SecureBootUEFI -ErrorAction Stop) { $SecureBoot = "SI" } else { $SecureBoot = "NO" }
    } catch { $SecureBoot = "NO/BIOS LEGACY" }
}

Write-Host "[OK] Hardware Detectado Correctamente" -ForegroundColor Green
Write-Host "-------------------------------------------"

Write-Host ""
$JuzgadoInput   = Read-Host "Ingrese el JUZGADO"
$EdificioInput  = Read-Host "Ingrese el EDIFICIO"
$PisoInput      = Read-Host "Ingrese el PISO/OFICINA"
$NombrePersonal = Read-Host "Ingrese el NOMBRE completo"
$Rol            = Read-Host "Ingrese el ROL del usuario"
$CodActPC       = Read-Host "Ingrese el CODIGO DE ACTIVO de la PC"

# --- Datos de la impresora (opcional) ---
$MarcaImp    = ""
$ModeloImp   = ""
$ConexionImp = ""
$CodActImp   = ""

Write-Host ""
$TieneImp = Read-Host "Tiene impresora? (S/N)"
if ($TieneImp -match '^[sS]') {
    $MarcaImp  = Read-Host "Ingrese la MARCA de la impresora"
    $ModeloImp = Read-Host "Ingrese el MODELO de la impresora"
    do {
        $ConexionInput = Read-Host "Conexion de la impresora (R = Red, U = USB)"
    } until ($ConexionInput -match '^[rRuU]')
    if ($ConexionInput -match '^[rR]') { $ConexionImp = "RED" } else { $ConexionImp = "USB" }
    $CodActImp = Read-Host "Ingrese el CODIGO DE ACTIVO de la impresora"
}

$Resultado = [PSCustomObject]@{
    "FECHA"                = (Get-Date -Format "yyyy-MM-dd HH:mm")
    "JUZGADO"              = $JuzgadoInput
    "EDIFICIO"             = $EdificioInput
    "PISO"                 = $PisoInput
    "HOSTNAME"             = $HostName
    "SERVICE_TAG"          = $ServiceTag
    "NOMBRE_USUARIO"       = $NombrePersonal
    "ROL"                  = $Rol
    "MARCA"                = $Marca
    "MODELO"               = $Modelo
    "PROCESADOR"           = $CpuInfo
    "TIPO_DISCO"           = $TipoDisco
    "TAMANO_DISCO"         = $TextoDisco
    "TIPO_RAM"             = $TipoRAM
    "TAMANO_MEMORIA"       = $TextoRAM
    "COD_ACT_PC"           = $CodActPC
    "MARCA_IMPRESORA"      = $MarcaImp
    "MODELO_IMPRESORA"     = $ModeloImp
    "CONEXION_IMPRESORA"   = $ConexionImp
    "COD_ACT_IMP"          = $CodActImp
    "TIPO_EQUIPO"          = $TipoEquipo
    "FECHA_BIOS"           = $FechaBios
    "VERSION_BIOS"         = $VersionBios
    "SO_NOMBRE"            = $SoNombre
    "SO_BUILD"             = $SoBuild
    "FECHA_INSTALACION_SO" = $FechaInsSO
    "CPU_NUCLEOS"          = $CpuNucleos
    "CPU_HILOS"            = $CpuHilos
    "CPU_MHZ"              = $CpuMhz
    "RAM_SLOTS_USADOS"     = $RamSlotsUsados
    "RAM_SLOTS_TOTAL"      = $RamSlotsTotal
    "RAM_MHZ"              = $RamMhz
    "DISCO_SALUD"          = $DiscoSalud
    "DISCO_SMART"          = $DiscoSmart
    "DISCO_DESGASTE_PCT"   = $DiscoDesgaste
    "DISCO_HORAS_USO"      = $DiscoHoras
    "DISCO_LIBRE_GB"       = $DiscoLibreGB
    "TPM_VERSION"          = $TpmVersion
    "SECURE_BOOT"          = $SecureBoot
    "IP"                   = $Ip
    "MAC"                  = $Mac
    "DOMINIO"              = $Dominio
}

$JsonData = $Resultado | ConvertTo-Json -Compress
$Bytes    = [System.Text.Encoding]::UTF8.GetBytes($JsonData)
$UrlAPI   = "__BASE_URL__/api/relevamiento"

try {
    Invoke-RestMethod -Uri $UrlAPI -Method Post -Body $Bytes -ContentType "application/json; charset=utf-8" | Out-Null
    Write-Host "[EXITO] Datos guardados directamente en Postgres!" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] No se pudo guardar en la base de datos central: $_" -ForegroundColor Red
}
Start-Sleep -Seconds 3
"""


@app.get("/script", response_class=PlainTextResponse)
def obtener_script(request: Request):
    base_url = str(request.base_url).rstrip("/")
    return SCRIPT_PS.replace("__BASE_URL__", base_url)


# --- 3. RECEPTOR DE LOS DATOS PARA INSERTAR EN POSTGRES ---
class EquipoData(BaseModel):
    FECHA: str
    JUZGADO: str
    EDIFICIO: str
    PISO: str
    HOSTNAME: str
    SERVICE_TAG: str
    NOMBRE_USUARIO: str
    ROL: str
    MARCA: str
    MODELO: str
    PROCESADOR: str
    TIPO_DISCO: str
    TAMANO_DISCO: str
    TIPO_RAM: str
    TAMANO_MEMORIA: str
    COD_ACT_PC: Optional[str] = None
    MARCA_IMPRESORA: Optional[str] = None
    MODELO_IMPRESORA: Optional[str] = None
    CONEXION_IMPRESORA: Optional[str] = None
    COD_ACT_IMP: Optional[str] = None
    TIPO_EQUIPO: Optional[str] = None
    FECHA_BIOS: Optional[str] = None
    VERSION_BIOS: Optional[str] = None
    SO_NOMBRE: Optional[str] = None
    SO_BUILD: Optional[str] = None
    FECHA_INSTALACION_SO: Optional[str] = None
    CPU_NUCLEOS: Optional[int] = None
    CPU_HILOS: Optional[int] = None
    CPU_MHZ: Optional[int] = None
    RAM_SLOTS_USADOS: Optional[int] = None
    RAM_SLOTS_TOTAL: Optional[int] = None
    RAM_MHZ: Optional[int] = None
    DISCO_SALUD: Optional[str] = None
    DISCO_SMART: Optional[str] = None
    DISCO_DESGASTE_PCT: Optional[int] = None
    DISCO_HORAS_USO: Optional[int] = None
    DISCO_LIBRE_GB: Optional[int] = None
    TPM_VERSION: Optional[str] = None
    SECURE_BOOT: Optional[str] = None
    IP: Optional[str] = None
    MAC: Optional[str] = None
    DOMINIO: Optional[str] = None


# La query se arma una sola vez a partir de COLUMNAS (nombres fijos, no vienen del usuario)
_cols = ", ".join(COLUMNAS)
_placeholders = ", ".join(["%s"] * len(COLUMNAS))
_updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNAS if c != "service_tag")
QUERY_UPSERT = f"""
    INSERT INTO equipos ({_cols})
    VALUES ({_placeholders})
    ON CONFLICT (service_tag) DO UPDATE SET {_updates};
"""


@app.post("/api/relevamiento")
def registrar_equipo(data: EquipoData):
    datos = dict(data)
    # Strings vacíos -> NULL (necesario para columnas DATE y más limpio para analizar)
    valores = [(datos[c.upper()] if datos[c.upper()] != "" else None) for c in COLUMNAS]

    try:
        with closing(conectar()) as conn, conn, conn.cursor() as cursor:
            cursor.execute(QUERY_UPSERT, valores)
        return {"status": "success"}
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar en la base de datos")


# --- 4. VISOR EN TIEMPO REAL DE EQUIPOS REGISTRADOS ---
def badge(texto, mal=False):
    clase = "badge-red" if mal else "badge-ok"
    return f'<span class="{clase}">{esc(texto)}</span>'


def armar_fila(f):
    """Convierte una fila (dict) de la BD en un <tr>."""
    # Impresora
    if f["marca_impresora"] or f["modelo_impresora"]:
        impresora = f"{esc(f['marca_impresora'])} {esc(f['modelo_impresora'])} ({esc(f['conexion_impresora'])})"
    else:
        impresora = "Sin impresora"

    # Antigüedad (según fecha del BIOS)
    if f["antiguedad_anios"] is None:
        antig = "—"
    else:
        antig = badge(f"{f['antiguedad_anios']} años", mal=float(f["antiguedad_anios"]) >= 6)

    # Salud del disco
    partes = []
    if f["disco_salud"]:
        partes.append(esc(f["disco_salud"]))
    if f["disco_desgaste_pct"] is not None:
        partes.append(f"desgaste {esc(f['disco_desgaste_pct'])}%")
    if f["disco_horas_uso"] is not None:
        partes.append(f"{esc(f['disco_horas_uso'])} h")
    disco_mal = (f["disco_salud"] not in (None, "", "Healthy")) or f["disco_smart"] == "FALLA"
    salud = badge(" · ".join(partes), mal=disco_mal) if partes else "—"

    # Disco, RAM, CPU
    libre = f" ({esc(f['disco_libre_gb'])} GB libres)" if f["disco_libre_gb"] is not None else ""
    slots = ""
    if f["ram_slots_usados"] is not None and f["ram_slots_total"] is not None:
        slots = f" [{esc(f['ram_slots_usados'])}/{esc(f['ram_slots_total'])} slots]"
    cpu_extra = ""
    if f["cpu_nucleos"] is not None:
        cpu_extra = f" ({esc(f['cpu_nucleos'])}C/{esc(f['cpu_hilos'])}T)"

    # Windows 11
    tpm = esc(f["tpm_version"]) or "?"
    sb = esc(f["secure_boot"]) or "?"

    return f"""
        <tr>
            <td>{esc(f['fecha'])}</td>
            <td><strong>{esc(f['juzgado'])}</strong></td>
            <td>{esc(f['edificio'])}</td>
            <td>{esc(f['piso'])}</td>
            <td><code>{esc(f['hostname'])}</code></td>
            <td><span class="badge-tag">{esc(f['service_tag'])}</span></td>
            <td>{esc(f['nombre_usuario'])}</td>
            <td>{esc(f['rol'])}</td>
            <td>{esc(f['marca'])} {esc(f['modelo'])} · {esc(f['tipo_equipo'])}</td>
            <td>{esc(f['procesador'])}{cpu_extra}</td>
            <td>{esc(f['tipo_disco'])} {esc(f['tamano_disco'])}{libre}</td>
            <td>{esc(f['tipo_ram'])} {esc(f['tamano_memoria'])}{slots}</td>
            <td>{antig}</td>
            <td>{esc(f['so_nombre'])} ({esc(f['so_build'])})</td>
            <td>{salud}</td>
            <td>TPM {tpm} / SB {sb}</td>
            <td>{esc(f['cod_act_pc'])}</td>
            <td>{impresora}</td>
            <td>{esc(f['cod_act_imp'])}</td>
        </tr>
    """


@app.get("/visor", response_class=HTMLResponse)
def ver_tabla_equipos():
    try:
        with closing(conectar()) as conn, conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT *,
                       ROUND((CURRENT_DATE - fecha_bios) / 365.25, 1) AS antiguedad_anios
                FROM equipos
                ORDER BY fecha DESC;
            """)
            filas = cursor.fetchall()
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Error al consultar la base de datos")

    total_equipos = len(filas)
    tabla_html = "".join(armar_fila(f) for f in filas)

    return f"""
    <html>
        <head>
            <title>Equipos Registrados</title>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 30px; background: #f4f6f9; color: #333; }}
                h1 {{ color: #2c3e50; }}
                .total {{ margin-bottom: 15px; font-weight: bold; color: #4a5568; }}
                .wrap {{ overflow-x: auto; background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
                th {{ background: #2c3e50; color: white; text-align: left; padding: 10px; white-space: nowrap; }}
                td {{ padding: 8px 10px; border-bottom: 1px solid #e2e8f0; }}
                tr:hover {{ background: #f7fafc; }}
                code {{ background: #edf2f7; padding: 2px 6px; border-radius: 4px; }}
                .badge-tag {{ background: #3182ce; color: white; padding: 2px 8px; border-radius: 10px; font-size: 12px; }}
                .badge-ok {{ background: #c6f6d5; color: #22543d; padding: 2px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }}
                .badge-red {{ background: #fed7d7; color: #742a2a; padding: 2px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }}
            </style>
        </head>
        <body>
            <h1>Equipos Registrados</h1>
            <p><a href="/">← Volver al inicio</a> &nbsp;|&nbsp; <a href="/exportar.csv">Descargar CSV (Excel / Power BI)</a></p>
            <div class="total">Total: {total_equipos}</div>
            <div class="wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Fecha</th><th>Juzgado</th><th>Edificio</th><th>Piso</th>
                            <th>Hostname</th><th>Service Tag</th><th>Usuario</th><th>Rol</th>
                            <th>Equipo</th><th>Procesador</th><th>Disco</th><th>RAM</th>
                            <th>Antigüedad</th><th>Sistema Operativo</th><th>Salud Disco</th><th>Win 11</th>
                            <th>Cód. Activo PC</th><th>Impresora</th><th>Cód. Activo Imp.</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tabla_html}
                    </tbody>
                </table>
            </div>
        </body>
    </html>
    """


# --- 5. EXPORTAR TODO A CSV PARA ANALISIS ---
@app.get("/exportar.csv")
def exportar_csv():
    try:
        with closing(conectar()) as conn, conn, conn.cursor() as cursor:
            cursor.execute("SELECT * FROM equipos ORDER BY fecha DESC;")
            columnas = [d[0] for d in cursor.description]
            filas = cursor.fetchall()
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Error al exportar")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columnas)
    writer.writerows(filas)

    # \ufeff (BOM) para que Excel respete tildes y ñ
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=equipos.csv"},
    )


if __name__ == "__main__":
    import uvicorn
    # Local: 127.0.0.1 | Red / Render: HOST=0.0.0.0 (en Render arranca con el startCommand de render.yaml)
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))