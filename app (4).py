"""
Streamlit dashboard para reporte de fallas por buque
==================================================

Esta aplicación de Streamlit se conecta a una hoja de cálculo de Google
contiene reportes de fallas de una flota. Carga los datos desde la
pestaña **Reportes de falla V2** y genera un tablero interactivo con un
tab por cada buque (barco). En cada sección se muestran gráficos de
distribución de fallas por departamento y por tipo de falla para cada
equipo o sistema, así como una tabla con los reportes abiertos.

Para que la aplicación lea los datos en tiempo real, la hoja debe
estar compartida con permisos de lectura para cualquiera que tenga el
enlace o bien se debe proporcionar una cuenta de servicio de Google en
el fichero `secrets.toml` de Streamlit. Se incluye un intento de
descarga directa mediante la URL de exportación a CSV (si la hoja es
pública). Si no es posible, se utiliza la librería `gspread` con
credenciales de servicio.

Configuración
-------------

En el código se definen las constantes `SHEET_ID` (identificador del
documento) y `GID` (identificador de la pestaña) que corresponden a la
pestaña *Reportes de falla V2*. Modifique estos valores si su
documento cambia.

Si la descarga directa a CSV no está permitida (error 403), se
habilitará un segundo intento mediante gspread. Para ello se deben
definir las credenciales del servicio en el archivo `secrets.toml` con
la clave `gcp_service_account`. Consulte la documentación de gspread
para más detalles.
"""

import os
from typing import Dict

import pandas as pd
import streamlit as st

try:
    # Importar plotly solo si está disponible. De lo contrario, se mostrará un mensaje de error.
    import plotly.express as px  # type: ignore
    PLOTLY_AVAILABLE = True
except Exception:
    PLOTLY_AVAILABLE = False

try:
    import gspread  # type: ignore
    from google.oauth2.service_account import Credentials  # type: ignore
    GSPREAD_AVAILABLE = True
except Exception:
    GSPREAD_AVAILABLE = False


# Identificadores de la hoja de cálculo
SHEET_ID = "178qdDSPP7GV3eISXE8xeN9MQtvV3fFk5efY1DCc8Tqk"
# GID de la pestaña "Reportes de falla V2"
GID = "58710399"


@st.cache_data(show_spinner=False)
def load_data(sheet_id: str = SHEET_ID, gid: str = GID) -> pd.DataFrame:
    """Carga los datos de la pestaña indicada del Google Sheet.

    Intenta primero descargar los datos usando el enlace de exportación CSV de
    Google Sheets【723629888661203†L160-L176】. Si falla (por ejemplo, la hoja no
    es pública), se utilizará `gspread` con las credenciales de servicio
    proporcionadas en `st.secrets`.

    Args:
        sheet_id: ID del documento.
        gid: ID de la pestaña.

    Returns:
        DataFrame con todos los registros de la pestaña o vacío si no se puede
        cargar.
    """
    # Intento 1: descargar mediante CSV si la hoja es pública
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        f"&id={sheet_id}&gid={gid}"
    )
    try:
        df = pd.read_csv(csv_url)
        # Si carga con éxito y no está vacío, devolver
        if not df.empty:
            return df
    except Exception:
        df = pd.DataFrame()

    # Intento 2: usar gspread con credenciales de servicio
    if GSPREAD_AVAILABLE and 'gcp_service_account' in st.secrets:
        try:
            creds_info: Dict[str, str] = st.secrets['gcp_service_account']  # type: ignore
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.readonly',
            ]
            credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
            client = gspread.authorize(credentials)
            spreadsheet = client.open_by_key(sheet_id)
            worksheet = spreadsheet.get_worksheet_by_id(int(gid))
            if worksheet is None:
                return df
            records = worksheet.get_all_records()
            df = pd.DataFrame(records)
            return df
        except Exception:
            pass

    # Fallback: devolver DataFrame vacío
    return pd.DataFrame()


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """Estandariza nombres de columnas y calcula campos auxiliares.

    Se normalizan los nombres de columnas a minúsculas sin espacios ni
    acentos para facilitar su uso. También se generan los campos `estado`
    (abierto, cerrado o cierre nave) y `dias_abierto` para los reportes sin
    fecha de cierre. En caso de que la estructura de columnas sea distinta,
    el comportamiento podría requerir ajustes manuales.

    Args:
        df: DataFrame original.

    Returns:
        DataFrame procesado con nombres normalizados y campos adicionales.
    """
    if df.empty:
        return df
    # Normalizar nombres de columnas: minúsculas, reemplazar espacios por guiones bajos
    df = df.rename(columns=lambda col: str(col).strip())
    # Crear un diccionario de renombrado para columnas de interés
    rename_map = {}
    for col in df.columns:
        col_lower = col.lower()
        if col_lower.startswith('depart'):
            rename_map[col] = 'departamento'
        elif col_lower.startswith('fecha falla') or col_lower == 'fecha falla':
            rename_map[col] = 'fecha_falla'
        elif col_lower.startswith('fecha de term'):
            rename_map[col] = 'fecha_cierre'
        elif col_lower.startswith('tipo de falla'):
            rename_map[col] = 'tipo_de_falla'
        elif col_lower.startswith('sistema'):
            rename_map[col] = 'sistema'
        elif col_lower.startswith('grupo'):
            rename_map[col] = 'grupo_area'
        elif col_lower.startswith('equipo') or col_lower.startswith('modelo equi'):
            rename_map[col] = 'equipo'
        elif col_lower.startswith('buque'):
            rename_map[col] = 'buque'
        elif col_lower.startswith('trabajo efectuado'):
            rename_map[col] = 'trabajo_efectuado'
        elif col_lower.startswith('descripcion de modo de falla'):
            rename_map[col] = 'descripcion_modo_falla'
    df = df.rename(columns=rename_map)
    # Convertir fechas si existen
    for date_col in ['fecha_falla', 'fecha_cierre']:
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce', dayfirst=True)
    # Calcular estado
    def determinar_estado(row):
        # Cerrado si existe fecha de cierre
        if 'fecha_cierre' in row and pd.notna(row['fecha_cierre']):
            return 'Cerrado'
        # Cierre de nave si el trabajo fue realizado por la nave
        trabajo = str(row.get('trabajo_efectuado', '')).strip().lower()
        if trabajo in ['nave', 'nave ']:
            return 'Cierre Nave'
        return 'Abierto'
    df['estado'] = df.apply(determinar_estado, axis=1)
    # Días abiertos: para reportes abiertos se calcula diferencia con hoy
    if 'fecha_falla' in df.columns:
        hoy = pd.Timestamp.today().normalize()
        df['dias_abierto'] = (hoy - df['fecha_falla']).dt.days
    return df


def draw_dashboard(df: pd.DataFrame) -> None:
    """Construye la interfaz del dashboard dado un DataFrame procesado."""
    if df.empty:
        st.error('No se pudo cargar la hoja de cálculo. Ajuste los permisos o credenciales.')
        return

    # Listar buques
    buques = sorted(df['buque'].dropna().unique().tolist()) if 'buque' in df.columns else []
    if not buques:
        st.error('No se encontraron datos de buques en la hoja.')
        return

    # Crear un tab por cada buque
    tabs = st.tabs([f"{buque}" for buque in buques])
    for buque, tab in zip(buques, tabs):
        with tab:
            df_buque = df[df['buque'] == buque].copy()
            st.subheader(f'Reportes de fallas: {buque}')

            # Distribución por departamento y estado
            if 'departamento' in df_buque.columns and 'estado' in df_buque.columns:
                dept_counts = (
                    df_buque.groupby(['departamento', 'estado'])
                    .size()
                    .reset_index(name='cantidad')
                )
                if PLOTLY_AVAILABLE and not dept_counts.empty:
                    fig_dept = px.bar(
                        dept_counts,
                        x='departamento',
                        y='cantidad',
                        color='estado',
                        barmode='group',
                        title='Estado de reportes por departamento'
                    )
                    st.plotly_chart(fig_dept, use_container_width=True)
                else:
                    st.bar_chart(
                        dept_counts.pivot(index='departamento', columns='estado', values='cantidad').fillna(0)
                    )

            # Barras apiladas por equipo y tipo de falla
            if 'equipo' in df_buque.columns and 'tipo_de_falla' in df_buque.columns:
                counts_equipo = (
                    df_buque.groupby(['equipo', 'tipo_de_falla'])
                    .size()
                    .reset_index(name='cantidad')
                )
                # Para evitar gráficos interminables, mostrar sólo los 10 equipos con más fallas
                top_equipos = (
                    counts_equipo.groupby('equipo')['cantidad']
                    .sum()
                    .nlargest(10)
                    .index
                )
                counts_equipo_top = counts_equipo[counts_equipo['equipo'].isin(top_equipos)]
                if PLOTLY_AVAILABLE and not counts_equipo_top.empty:
                    fig_equipo = px.bar(
                        counts_equipo_top,
                        x='equipo',
                        y='cantidad',
                        color='tipo_de_falla',
                        barmode='stack',
                        title='Fallas por equipo y tipo de falla (top 10 equipos)'
                    )
                    st.plotly_chart(fig_equipo, use_container_width=True)
                else:
                    pivot = counts_equipo_top.pivot(index='equipo', columns='tipo_de_falla', values='cantidad').fillna(0)
                    st.bar_chart(pivot)

            # Barras apiladas por sistema y tipo de falla
            if 'sistema' in df_buque.columns and 'tipo_de_falla' in df_buque.columns:
                counts_sistema = (
                    df_buque.groupby(['sistema', 'tipo_de_falla'])
                    .size()
                    .reset_index(name='cantidad')
                )
                top_sistemas = (
                    counts_sistema.groupby('sistema')['cantidad']
                    .sum()
                    .nlargest(10)
                    .index
                )
                counts_sistema_top = counts_sistema[counts_sistema['sistema'].isin(top_sistemas)]
                if PLOTLY_AVAILABLE and not counts_sistema_top.empty:
                    fig_sistema = px.bar(
                        counts_sistema_top,
                        x='sistema',
                        y='cantidad',
                        color='tipo_de_falla',
                        barmode='stack',
                        title='Fallas por sistema y tipo de falla (top 10 sistemas)'
                    )
                    st.plotly_chart(fig_sistema, use_container_width=True)
                else:
                    pivot = counts_sistema_top.pivot(index='sistema', columns='tipo_de_falla', values='cantidad').fillna(0)
                    st.bar_chart(pivot)

            # Tabla de informes de falla abiertos
            if 'estado' in df_buque.columns:
                df_abierto = df_buque[df_buque['estado'] == 'Abierto'].copy()
                # Seleccionar columnas de interés
                cols = []
                for c in ['departamento', 'fecha_falla', 'dias_abierto', 'equipo', 'descripcion_modo_falla']:
                    if c in df_abierto.columns:
                        cols.append(c)
                if cols:
                    st.subheader('Reportes de falla abiertos')
                    st.dataframe(df_abierto[cols], use_container_width=True)


def main() -> None:
    st.set_page_config(page_title='Dashboard de fallas por buque', layout='wide')
    st.title('Dashboard de fallas por buque')
    st.markdown(
        'Esta aplicación se conecta a un Google Sheet para mostrar reportes de '
        'fallas de una flota. Puede analizar las fallas por barco, departamento, '
        'sistema, equipo y tipo de falla. Para modificar los datos en tiempo '
        'real, edite la hoja en Google Sheets; los cambios se reflejarán al '
        'recargar esta página.'
    )
    # Botón para forzar recarga de datos
    if st.button('Recargar datos', help='Refresca los datos desde Google Sheets'):
        st.cache_data.clear()
    df_raw = load_data()
    df_processed = preprocess(df_raw)
    draw_dashboard(df_processed)


if __name__ == '__main__':
    main()