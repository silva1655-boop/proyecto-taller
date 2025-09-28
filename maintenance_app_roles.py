"""
Maintenance Management Application with Role‑based Interface
------------------------------------------------------------

This Streamlit application extends the earlier maintenance
management prototype to support **role‑based views**.  On launch
the user may choose between two primary roles:

* **Mantenimiento** – intended for workshop and maintenance
  personnel.  It exposes tools to create and schedule work
  orders, process requests from operations, manage the
  inventory, record failures and track reliability metrics.

* **Terminales (Operaciones)** – intended for operations or
  terminal users who operate the trucks.  This view provides
  visibility into the current status of the fleet, allows
  operators to submit work requests with criticality and
  telemetry (horómetro), and to perform daily check lists to
  update hour and kilometre readings.

Both roles share a common **dashboard** summarising the fleet
status (total equipment, availability, equipment close to
scheduled maintenance and equipment currently in maintenance).

The application builds on top of the maintenance classes
defined in ``maintenance_program.py`` and uses Streamlit's
widgets to create interactive forms and tables.  All data is
stored in the Streamlit session state for the duration of the
session.  In a production environment you would replace
session state with persistent storage (e.g. a database or
cloud storage service).

To run the application:

1. Ensure Python 3.8+ is available and install Streamlit:

   ``pip install streamlit``

2. Place this file alongside ``maintenance_program.py`` in the
   same directory.

3. Launch the app with:

   ``streamlit run maintenance_app_roles.py``

4. The app will open in your browser.  Select your role
   (Mantenimiento or Terminales) from the sidebar.  The
   available functionality will adjust accordingly.

This code is meant as a starting point and can be tailored to
specific workflows.  For example, you could add user
authentication, integrate with an external inventory system
through an API, or implement a persistent database layer.
"""

import datetime
import calendar
import os
import uuid
import json
from typing import Dict, List, Tuple

import streamlit as st
import pandas as pd

from maintenance_program import (
    Component,
    Equipment,
    Scheduler,
    Inventory,
    FailureLog,
    WorkOrder,
)

# Import for password hashing if needed in the future (unused in this demo)
import hashlib
import base64

# ---------------------------------------------------------------------------
# Utility functions

def play_alert_sound() -> None:
    """Play a short embedded alert tone.

    To improve reliability across different environments we embed a
    base64‑encoded WAV file directly in the source code.  When an
    alert is triggered the audio is decoded and passed to
    ``st.audio``, which causes it to play immediately in the user's
    browser.  If audio playback is not supported (for example,
    because the page is not focused), the function silently
    ignores the exception.
    """
    # Base64 representation of a 0.2 second beep tone.  This value can
    # be replaced with your own sound: use
    # ``base64.b64encode(open('beep.wav','rb').read()).decode()``.
    BEEP_BASE64 = (
        "UklGRgxFAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YehEAAAAAAAAPwAA"
        "PT8AAP7/AAH+fwAC/n4AB/9+ABX/fgAZ/34AIf5+ADI/fgArPn4AHj1+AB08fgAZPH4A"
        "DDp+ABs3fgAkMH4AEzV+AAQxfv8BPn3/AT99/wH/fv8C/n7/A/9+/wT/ff8E/3//BP9/"
        "AAf/fP8H/nz/CP98/ws/ngMO/3kDEv14Awj9YQL//GEEQ/hsBGn4agRw9HoGdORefkzjX"
        "35k5z9/POf4zzrQM9Uyz+SvOLsYkx8SMYXPgFkeMPlG5g0Pb/X8YISJbh4HpL8dRpGvQU"
        "Mp+xcQ=="
    )
    try:
        # Construct an HTML audio tag with the embedded base64 data.
        # The ``autoplay`` attribute asks the browser to play the sound
        # immediately.  Many browsers require user interaction before
        # playing sound; if autoplay fails, the widget simply does not
        # render.  Setting ``hidden`` hides the controls.
        audio_tag = f"""
<audio autoplay hidden>
    <source src="data:audio/wav;base64,{BEEP_BASE64}" type="audio/wav">
</audio>
"""
        st.markdown(audio_tag, unsafe_allow_html=True)
    except Exception:
        # On failure fall back to the interactive audio player
        import base64 as _b64
        audio_bytes = _b64.b64decode(BEEP_BASE64)
        st.audio(audio_bytes, format="audio/wav")


def send_email_notification(to_address: str, subject: str, message: str) -> None:
    """Stub function to send an email notification.

    In a production deployment you would configure SMTP credentials and
    implement the logic here using Python's ``smtplib`` or a third‑party
    service.  For this demo the function simply logs the intended
    recipient and subject to the Streamlit interface.  Adjust this
    implementation to integrate with your mail server.

    Parameters
    ----------
    to_address : str
        Email address of the recipient.
    subject : str
        Subject line for the email.
    message : str
        Body text of the email.
    """
    # In this demonstration we simply inform the user via the UI.
    st.info(f"Correo enviado a {to_address} – {subject}")

# ---------------------------------------------------------------------------
# Audio alert configuration
#
# The application can play a short beep sound when new notifications arrive.
# A small WAV file (beep.wav) is bundled with this project.  The file is
# generated automatically in the repository and loaded at runtime.  If the
# file is missing the audio alert will be silently skipped.  Users can
# replace this file with any other short alert sound if desired.


# ---------------------------------------------------------------------------
# User authentication configuration.
#
# Each entry in USERS defines a username, its password and the role assigned
# to that user.  For demonstration purposes the passwords are stored in
# plain text.  In a real system you would store hashed passwords and
# validate them securely.
USERS: Dict[str, Dict[str, str]] = {
    "mantenimiento": {"password": "1234", "role": "Mantenimiento"},
    "operaciones": {"password": "1234", "role": "Terminales"},
}

# Path to the company logo.  The image file ``descarga.png`` should be
# placed in the same directory as this script or in the current
# working directory.  If the file exists it will be displayed in the
# sidebar.  Adjust the filename if you rename the image.
LOGO_PATH = os.path.join(os.path.dirname(__file__), "descarga.png")

# Path to persist application data.  When running the application
# outside of this repository you can change the filename or location.
DATA_FILE = os.path.join(os.path.dirname(__file__), "maintenance_data.json")


def init_state() -> None:
    """Initialise the Streamlit session state.

    This function populates the session state with the core data
    structures: the fleet of equipment, inventory, scheduler,
    failure log, work requests from operations and notifications.

    It also seeds a few default components and spare parts so the
    demonstration is functional from the outset.  In a real
    deployment these defaults would be loaded from a database or
    configuration file.
    """
    if "fleet" not in st.session_state:
        st.session_state.fleet: Dict[str, Equipment] = {}
        st.session_state.inventory = Inventory()
        st.session_state.scheduler = Scheduler(
            st.session_state.fleet, st.session_state.inventory
        )
        st.session_state.failure_log = FailureLog()
        st.session_state.work_requests: List[Dict] = []
        st.session_state.notifications_ops: List[str] = []
        # Define some default components with maintenance intervals.
        st.session_state.default_components = {
            "Amortiguadores": Component(
                "Amortiguadores",
                "alta",
                hours_interval=500,
                km_interval=50000,
                days_interval=365,
            ),
            "Limpiaparabrisas": Component(
                "Limpiaparabrisas",
                "alta",
                hours_interval=200,
                km_interval=None,
                days_interval=180,
            ),
            "Luces": Component(
                "Luces",
                "alta",
                hours_interval=None,
                km_interval=None,
                days_interval=90,
            ),
        }
        # Seed the inventory with a few items
        st.session_state.inventory.add_part(
            "Amortiguador delantero",
            initial_stock=10,
            min_stock=2,
            fits_components=["Amortiguadores"],
        )
        st.session_state.inventory.add_part(
            "Plumillas limpiaparabrisas",
            initial_stock=20,
            min_stock=5,
            fits_components=["Limpiaparabrisas"],
        )
        st.session_state.inventory.add_part(
            "Foco delantero",
            initial_stock=30,
            min_stock=5,
            fits_components=["Luces"],
        )

        # -----------------------------------------------------------------
        # Define component categories for grouping components by system.
        # These mappings allow the UI to present a first drop‑down with
        # categories (sistemas) and a second drop‑down with components
        # belonging to the selected category.  If a category has no
        # predefined components it will present an empty list (a text
        # input may be used instead).
        st.session_state.component_categories = {
            "Suspensión": ["Amortiguadores"],
            "Cabina": ["Limpiaparabrisas", "Luces"],
            "Motor": [],
            "Transmisión": [],
            "Tren delantero": [],
            "Tren trasero": [],
            "Frenos": [],
            "Otros": [],
        }

        # -----------------------------------------------------------------
        # Seed the fleet with the list of equipment IDs provided by the user
        # If the fleet is empty (first launch), automatically register
        # the predefined tractors.  These IDs correspond to three makes:
        # Terberg (prefix T), Kalmar (prefix K) and MOL (prefix M).
        default_ids = [
            "T648", "T659", "T779", "T789", "T73", "T74",
            "K69", "K71", "K72", "K73", "K75", "K76",
            "M01", "M02", "M03", "M04",
        ]
        for eq_id in default_ids:
            # Determine description based on prefix
            if eq_id.startswith("T"):
                brand = "Terberg"
            elif eq_id.startswith("K"):
                brand = "Kalmar"
            elif eq_id.startswith("M"):
                brand = "MOL"
            else:
                brand = "Tracto"
            description = f"Tracto {brand}"
            # Create and register equipment only if not already present
            if eq_id not in st.session_state.fleet:
                new_eq = Equipment(eq_id, description)
                # Register default components for each predefined tractor
                for comp in st.session_state.default_components.values():
                    new_eq.register_component(comp)
                st.session_state.fleet[eq_id] = new_eq
    # ensure new structures exist in case of hot reload
    if "work_requests" not in st.session_state:
        st.session_state.work_requests = []
    if "notifications_ops" not in st.session_state:
        st.session_state.notifications_ops = []
    # Track the number of operations notifications last seen by the user.
    # This allows us to play an alert sound only when new messages arrive.
    if "last_notif_count_ops" not in st.session_state:
        st.session_state.last_notif_count_ops = 0

    # Similarly track the number of items relevant to maintenance users
    # (pending work requests and newly scheduled orders).  When this count
    # increases the maintenance dashboard will play an alert tone to
    # notify the user of new work.  Without this counter it would be
    # difficult to detect only new requests.
    if "last_notif_count_mtto" not in st.session_state:
        st.session_state.last_notif_count_mtto = 0

    # Always attempt to load persisted state from disk at the end of
    # initialisation.  This ensures that updates made by other
    # sessions (possibly on another computer) are reflected in the
    # current session.  Any missing file or parsing errors are
    # silently ignored.  Default components and categories remain
    # registered so that new equipment can still be seeded on first
    # launch.
    try:
        load_data()
    except Exception:
        pass


def add_equipment_form() -> None:
    """Render a form to register new equipment.

    Each new tractor is automatically assigned the default
    components configured in the session state.  Equipment IDs
    must be unique.  The operator enters an ID and a
    description.  On submission, the equipment is stored in the
    session state.  This function intentionally omits any
    heading so that callers can provide their own context or
    heading outside the form.
    """
    with st.form(key="add_equipment_form"):
        eq_id = st.text_input("ID del equipo", value="T")
        eq_desc = st.text_input("Descripción", value="Tracto")
        submitted = st.form_submit_button("Añadir equipo")
        if submitted:
            if not eq_id:
                st.error("El ID no puede estar vacío")
            elif eq_id in st.session_state.fleet:
                st.error(f"Ya existe un equipo con ID {eq_id}")
            else:
                new_eq = Equipment(eq_id, eq_desc)
                for comp in st.session_state.default_components.values():
                    new_eq.register_component(comp)
                st.session_state.fleet[eq_id] = new_eq
                # Persist new equipment to disk
                save_data()
                st.success(f"Equipo {eq_id} registrado correctamente")


def update_readings_form() -> None:
    """Form to update horometro and odometro readings for a selected equipment."""
    if not st.session_state.fleet:
        st.info("No hay equipos registrados.")
        return
    eq_ids = list(st.session_state.fleet.keys())
    selected = st.selectbox("Seleccionar equipo", eq_ids, key="upd_sel_eq")
    eq = st.session_state.fleet[selected]
    st.write(
        f"Horómetro actual: {eq.horometro:.1f} h | Odómetro actual: {eq.odometro:.1f} km"
    )
    add_hours = st.number_input(
        "Horas adicionales", min_value=0.0, step=0.5, key="upd_hours"
    )
    add_km = st.number_input(
        "Kilómetros adicionales", min_value=0.0, step=0.5, key="upd_km"
    )
    if st.button("Actualizar lecturas", key="upd_btn"):
        eq.update_horometro(add_hours)
        eq.update_odometro(add_km)
        # Persist updates to disk
        save_data()
        st.success(
            f"Equipo {eq.id}: horómetro +{add_hours} h, odómetro +{add_km} km"
        )


def fleet_summary() -> Tuple[int, int, int, int]:
    """Compute summary statistics for the fleet.

    Returns a tuple with (total_equipment, available, due_soon, in_maintenance).
    """
    total = len(st.session_state.fleet)
    available = 0
    in_maintenance = 0
    due_soon = 0
    # Consider orders due within the next 7 days as "próximos a mantenimiento"
    horizon = datetime.date.today() + datetime.timedelta(days=7)
    # Determine which equipment has pending work requests.  Any unit with a
    # pending request should not be considered available, even if its status
    # remains "operativo".  This ensures that a unit reported by operations
    # appears as out of service until maintenance processes it.
    pending_req_ids = set(
        req["equipment_id"]
        for req in st.session_state.work_requests
        if req.get("status") == "pendiente"
    )
    for eq in st.session_state.fleet.values():
        # Only count units as available if they are operational and have no
        # outstanding requests
        if eq.status == "operativo" and eq.id not in pending_req_ids:
            available += 1
        if eq.status == "en mantenimiento":
            in_maintenance += 1
    # pending scheduled orders due soon
    for order in st.session_state.scheduler.pending_orders:
        if order.status == "pendiente" and order.due_date <= horizon:
            due_soon += 1
    return total, available, due_soon, in_maintenance


def render_calendar(pending_orders: List[WorkOrder]) -> str:
    """Render a simple HTML calendar for the current month.

    The calendar highlights dates with pending work orders and shows
    the number of tasks due on that date.  It uses Python's
    ``calendar`` module to build a table.  Only orders with
    ``status`` equal to ``pendiente`` are considered.  Days with
    no tasks are displayed normally.  The returned string can be
    passed directly to ``st.markdown`` with ``unsafe_allow_html=True``.

    Args:
        pending_orders: list of WorkOrder objects representing
            scheduled maintenance orders.

    Returns:
        A string containing HTML for the calendar.
    """
    today = datetime.date.today()
    year, month = today.year, today.month
    # Map day number to count of pending orders due on that day
    tasks_by_day: Dict[int, int] = {}
    for order in pending_orders:
        # Only consider pending orders scheduled in the current month
        if (
            order.status == "pendiente"
            and order.due_date.year == year
            and order.due_date.month == month
        ):
            tasks_by_day[order.due_date.day] = tasks_by_day.get(order.due_date.day, 0) + 1
    # Build the calendar as a table.  We set a simple inline CSS
    # style for borders and spacing.  Days with tasks get a red
    # background and display the task count beneath the day number.
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(year, month)
    html = [
        '<table style="border-collapse: collapse; width: 100%; text-align: center;">',
        f'<caption style="margin-bottom: 8px; font-weight: bold;">{calendar.month_name[month]} {year}</caption>',
        '<thead><tr>'
    ]
    for day_name in ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]:
        html.append(
            f'<th style="border: 1px solid #ddd; padding: 4px; background-color: #f5f5f5;">{day_name}</th>'
        )
    html.append('</tr></thead><tbody>')
    for week in weeks:
        html.append('<tr>')
        for day in week:
            if day == 0:
                # Empty cell (days outside the current month)
                html.append('<td style="border: 1px solid #ddd; padding: 8px; height: 60px;"></td>')
            else:
                # Determine if there are tasks on this day
                count = tasks_by_day.get(day)
                if count:
                    # Highlight cell with a red background and white text
                    cell_style = (
                        "border: 1px solid #ddd; padding: 4px; height: 60px; "
                        "background-color: #f8d7da; color: #721c24;"
                    )
                    content = f'<strong>{day}</strong><br/><span style="font-size: 0.8em;">{count} OT</span>'
                else:
                    cell_style = "border: 1px solid #ddd; padding: 4px; height: 60px;"
                    content = f"{day}"
                html.append(f'<td style="{cell_style}">{content}</td>')
        html.append('</tr>')
    html.append('</tbody></table>')
    return "".join(html)


def serialize_session_state() -> Dict[str, object]:
    """Serialize the current session state into a JSON-serialisable structure.

    This function converts complex objects (Equipment, Components, WorkOrders, etc.)
    into dictionaries of primitive data types (strings, numbers, lists) so they
    can be persisted to disk.  Date and datetime objects are converted to ISO
    formatted strings.  Only data that needs to persist is included; UI state
    such as selected tabs or temporary inputs is not saved.

    Returns
    -------
    dict
        A dictionary representing the current session state.
    """
    data: Dict[str, object] = {}
    # Serialize fleet
    fleet_data = {}
    for eq_id, eq in st.session_state.fleet.items():
        components_data = []
        for rec in eq.components.values():
            comp = rec.component
            components_data.append({
                "name": comp.name,
                "criticidad": comp.criticidad,
                "hours_interval": comp.hours_interval,
                "km_interval": comp.km_interval,
                "days_interval": comp.days_interval,
                "last_service_date": rec.last_service_date.isoformat(),
                "last_service_hours": rec.last_service_hours,
                "last_service_km": rec.last_service_km,
            })
        fleet_data[eq_id] = {
            "description": eq.description,
            "horometro": eq.horometro,
            "odometro": eq.odometro,
            "status": eq.status,
            "components": components_data,
        }
    data["fleet"] = fleet_data
    # Serialize inventory
    inv_data = {}
    for part_name, (qty, min_qty) in st.session_state.inventory._stock.items():
        inv_data[part_name] = {
            "stock": qty,
            "min_stock": min_qty,
            "fits_components": st.session_state.inventory._part_mapping.get(part_name, []),
        }
    data["inventory"] = inv_data
    # Serialize pending work orders
    orders_data = []
    for order in st.session_state.scheduler.pending_orders:
        orders_data.append({
            "id": order.id,
            "equipment_id": order.equipment_id,
            "component_name": order.component_name,
            "due_date": order.due_date.isoformat(),
            "reason": order.reason,
            "classification": getattr(order, "classification", ""),
            # Safely access materials_used if present
            "materials_used": getattr(order, "materials_used", []),
            "status": order.status,
            "created_at": order.created_at.isoformat(),
            # Safely serialise completed_at and start_time.  Some WorkOrder
            # implementations may not define these attributes.  Use getattr
            # with a default of None to avoid AttributeError.  When
            # present, convert to ISO string; otherwise store None.
            "completed_at": (
                getattr(order, "completed_at", None).isoformat() if getattr(order, "completed_at", None) else None
            ),
            "start_time": (
                getattr(order, "start_time", None).isoformat() if getattr(order, "start_time", None) else None
            ),
        })
    data["pending_orders"] = orders_data
    # Serialize work requests
    requests_data = []
    for req in st.session_state.work_requests:
        requests_data.append({
            **req,
            "date": req["date"].isoformat() if isinstance(req["date"], datetime.date) else req["date"],
        })
    data["work_requests"] = requests_data
    # Serialize failure log
    failures_data = []
    for entry in st.session_state.failure_log.entries:
        ts, eq_id, comp, desc, repair = entry
        failures_data.append({
            "timestamp": ts.isoformat(),
            "equipment_id": eq_id,
            "component_name": comp,
            "description": desc,
            "repair_time_hours": repair,
        })
    data["failures"] = failures_data
    # Notifications to operations
    data["notifications_ops"] = list(st.session_state.notifications_ops)
    # Persist the user credentials so that password changes survive
    # across sessions.  Note: passwords are stored in plain text for
    # demonstration purposes.  In a production system you should
    # store password hashes instead.
    data["users"] = USERS
    return data


def save_data() -> None:
    """Persist the current session state to disk.

    This function writes a JSON file containing the serialised session state
    to the path defined in ``DATA_FILE``.  If any error occurs (e.g., lack of
    write permissions), the exception is silently ignored.  In a production
    environment you should log or handle such errors explicitly.
    """
    try:
        data = serialize_session_state()
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # Ignore persistence errors in this demo
        pass


def load_data() -> None:
    """Load persisted session state from disk if available.

    This function reads the JSON file defined by ``DATA_FILE`` and
    reconstructs equipment, inventory, pending orders, requests and failures.
    If the file does not exist or cannot be parsed, the function returns
    without modifying the session state.  Existing data in ``st.session_state``
    is replaced with the persisted data where applicable.
    """
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    # Load fleet
    fleet_data = data.get("fleet", {})
    # Clear existing fleet before loading
    st.session_state.fleet = {}
    for eq_id, eq_info in fleet_data.items():
        eq = Equipment(eq_id, eq_info.get("description", "Tracto"))
        eq.horometro = eq_info.get("horometro", 0.0)
        eq.odometro = eq_info.get("odometro", 0.0)
        eq.status = eq_info.get("status", "operativo")
        # Reconstruct components
        for comp_info in eq_info.get("components", []):
            comp = Component(
                comp_info["name"],
                comp_info.get("criticidad", "media"),
                comp_info.get("hours_interval"),
                comp_info.get("km_interval"),
                comp_info.get("days_interval"),
            )
            # Register with last service info
            last_date = datetime.date.fromisoformat(comp_info["last_service_date"])
            last_hours = comp_info.get("last_service_hours", 0.0)
            last_km = comp_info.get("last_service_km", 0.0)
            eq.register_component(
                comp, service_date=last_date, service_hours=last_hours, service_km=last_km
            )
        st.session_state.fleet[eq_id] = eq
    # Load inventory
    inv_data = data.get("inventory", {})
    st.session_state.inventory = Inventory()
    for part_name, info in inv_data.items():
        st.session_state.inventory.add_part(
            part_name,
            info.get("stock", 0),
            info.get("min_stock", 0),
            info.get("fits_components", []),
        )
    # Load scheduler and pending orders
    st.session_state.scheduler = Scheduler(st.session_state.fleet, st.session_state.inventory)
    orders_data = data.get("pending_orders", [])
    for od in orders_data:
        wo = WorkOrder(
            equipment_id=od["equipment_id"],
            component_name=od["component_name"],
            due_date=datetime.date.fromisoformat(od["due_date"]),
            reason=od.get("reason", ""),
            classification=od.get("classification", ""),
        )
        # Set additional attributes
        wo.id = od.get("id", wo.id)
        wo.materials_used = od.get("materials_used", [])
        wo.status = od.get("status", "pendiente")
        wo.created_at = datetime.datetime.fromisoformat(od.get("created_at", datetime.datetime.now().isoformat()))
        if od.get("completed_at"):
            wo.completed_at = datetime.datetime.fromisoformat(od["completed_at"])
        if od.get("start_time"):
            wo.start_time = datetime.datetime.fromisoformat(od["start_time"])
        st.session_state.scheduler.pending_orders.append(wo)
    # Load work requests
    st.session_state.work_requests = []
    for req in data.get("work_requests", []):
        # Convert date field back to date object
        req_copy = dict(req)
        if req_copy.get("date"):
            try:
                req_copy["date"] = datetime.date.fromisoformat(req_copy["date"])
            except ValueError:
                pass
        st.session_state.work_requests.append(req_copy)
    # Load failure log
    st.session_state.failure_log = FailureLog()
    for entry in data.get("failures", []):
        try:
            ts = datetime.datetime.fromisoformat(entry["timestamp"])
        except Exception:
            ts = datetime.datetime.now()
        st.session_state.failure_log.entries.append(
            (ts, entry["equipment_id"], entry["component_name"], entry["description"], entry["repair_time_hours"])
        )
    # Load notifications to operations
    st.session_state.notifications_ops = data.get("notifications_ops", [])
    # Load user credentials if present
    users_data = data.get("users")
    if users_data:
        # Overwrite the global USERS dictionary
        for uname, info in users_data.items():
            USERS[uname] = info


def display_dashboard() -> None:
    """Display a common dashboard with fleet status metrics.

    This dashboard appears for both roles and shows counts of
    total equipment, available (operational) equipment, equipment
    with maintenance coming due soon, and those currently in
    maintenance.  It also includes a table with detailed
    information about each tractor.
    """
    total, available, due_soon, in_maintenance = fleet_summary()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total equipos", total)
    col2.metric("Disponibles", available)
    col3.metric("Próx. a mantenimiento", due_soon)
    col4.metric("En mantenimiento", in_maintenance)
    # Table of fleet status
    if st.session_state.fleet:
        # Determine per‑equipment status with icons
        # Identify equipment with orders due soon (within 7 days)
        horizon = datetime.date.today() + datetime.timedelta(days=7)
        due_soon_eq = {
            order.equipment_id
            for order in st.session_state.scheduler.pending_orders
            if order.status == "pendiente" and order.due_date <= horizon
        }
        # Identify equipment with high‑priority pending requests (falla)
        fail_eq = {
            req["equipment_id"]
            for req in st.session_state.work_requests
            if req.get("status") == "pendiente" and req.get("classification") == "alta"
        }
        # Identify all equipment with pending requests (any classification)
        pending_all = {
            req["equipment_id"]
            for req in st.session_state.work_requests
            if req.get("status") == "pendiente"
        }
        # Equipment with non‑high requests (solicitudes)
        solicit_eq = pending_all - fail_eq
        rows = []
        for eq in st.session_state.fleet.values():
            # Determine icon and label based on multiple conditions
            if eq.id in fail_eq:
                icon = "🚨"
                label = "Falla"
            elif eq.status == "en mantenimiento":
                icon = "🔧"
                label = "Mantenimiento"
            elif eq.id in solicit_eq:
                icon = "🟠"
                label = "Solicitud"
            elif eq.id in due_soon_eq:
                icon = "🟡"
                label = "Próx. mant."
            else:
                icon = "🟢"
                label = "Operativo"
            rows.append(
                {
                    "ID": eq.id,
                    "Descripción": eq.description,
                    "Horómetro (h)": f"{eq.horometro:.1f}",
                    "Odómetro (km)": f"{eq.odometro:.1f}",
                    "Estado": f"{icon} {label}",
                }
            )
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("No hay equipos registrados.")
    # Render a simple calendar of scheduled work orders for the current month.
    # This calendar highlights dates with pending maintenance orders.  The
    # number of orders due on a given day is displayed under the date.
    calendar_html = render_calendar(st.session_state.scheduler.pending_orders)
    st.markdown(calendar_html, unsafe_allow_html=True)


def operations_view() -> None:
    """Render the interface for operations users.

    This view uses internal tabs to organise content:
    * **Resumen**: Dashboard and notifications.
    * **Crear OT**: Form for submitting new work requests.
    * **Seguimiento OT**: Tables showing pending requests and work orders.
    * **Checklist diario**: Form to update horómetro and odómetro readings.
    * **Historial de fallas**: Display logged failures for selected equipment.
    * **Disponibilidad**: Bar chart of fleet status categories.
    """
    st.header("Terminales / Operaciones")
    # Manual refresh button to reload the app state.  This is useful when
    # running without the streamlit_autorefresh extension or when
    # simultaneous sessions need to pull the latest data from disk.
    if st.button("Refrescar ahora", key="ops_refresh_btn"):
        st.experimental_rerun()

    # Enable automatic refresh every 5 seconds so that operations users
    # receive newly persisted notifications or state changes without
    # manual reloading.  The refresh is keyed to prevent multiple
    # refreshers from being created on rerun.
    try:
        from streamlit_autorefresh import st_autorefresh  # type: ignore

        st_autorefresh(interval=5000, key="ops_autorefresh")
    except Exception:
        # If the extension is unavailable, no automatic refresh will occur.
        pass
    tabs = st.tabs(
        [
            "Resumen",
            "Crear OT",
            "Seguimiento OT",
            "Checklist diario",
            "Historial de fallas",
            "Disponibilidad",
        ]
    )

    # Tab 0: Summary and notifications
    with tabs[0]:
        st.subheader("Resumen de flota")
        display_dashboard()
        # Notifications from maintenance
        # Only show the notification heading if there are messages.
        notif_list = st.session_state.notifications_ops
        if notif_list:
            # Check if new notifications arrived since last rendering.
            new_count = len(notif_list)
            if new_count > st.session_state.last_notif_count_ops:
                # Play an audio alert to draw attention.
                play_alert_sound()
            st.session_state.last_notif_count_ops = new_count
            st.subheader("Notificaciones recientes de mantenimiento")
            for msg in notif_list:
                st.info(msg)
            if st.button("Marcar como leídas", key="ops_notif_read"):
                # Clear notifications and persist the state so other sessions
                # do not show already read messages.  This action resets the
                # counter to zero.
                st.session_state.notifications_ops = []
                st.session_state.last_notif_count_ops = 0
                save_data()

    # Tab 1: Create OT request
    with tabs[1]:
        st.subheader("Crear solicitud de mantenimiento")
        if not st.session_state.fleet:
            st.info("Debe registrar al menos un equipo para crear solicitudes.")
        else:
            req_id = uuid.uuid4().hex
            eq_sel = st.selectbox(
                "Equipo", list(st.session_state.fleet.keys()), key="ops_req_eq"
            )
            # Select system (category) first, then component belonging to that system
            categories = list(st.session_state.component_categories.keys())
            system_sel = st.selectbox(
                "Sistema", categories, key="ops_req_sys"
            )
            comp_options = st.session_state.component_categories.get(system_sel, [])
            if comp_options:
                comp_sel = st.selectbox(
                    "Componente", comp_options, key="ops_req_comp"
                )
            else:
                # If no components defined for the selected system, allow free text
                comp_sel = st.text_input(
                    "Componente", key="ops_req_comp_text"
                )
            classification = st.selectbox(
                "Criticidad", ["alta", "media", "baja"], key="ops_req_class"
            )
            comments = st.text_area(
                "Comentarios / descripción de la falla", key="ops_req_comments"
            )
            horometro = st.number_input(
                "Lectura actual de horómetro (h)", min_value=0.0, step=0.5, key="ops_req_hr"
            )
            date_report = st.date_input(
                "Fecha de reporte", value=datetime.date.today(), key="ops_req_date"
            )
            photo = st.file_uploader(
                "Adjuntar foto (opcional)", type=["jpg", "jpeg", "png"], key="ops_req_photo"
            )
            if st.button("Enviar solicitud", key="ops_req_submit"):
                # Construct a new work request record
                req = {
                    "id": req_id,
                    "equipment_id": eq_sel,
                    "component_name": comp_sel,
                    "classification": classification,
                    "comments": comments,
                    "photo_name": photo.name if photo else None,
                    "horometro": horometro,
                    "date": date_report,
                    "status": "pendiente",
                    "created_at": datetime.datetime.now(),
                }
                # Append the request to the list
                st.session_state.work_requests.append(req)
                # When a request is submitted, mark the equipment as unavailable
                eq_obj = st.session_state.fleet.get(eq_sel)
                if eq_obj and eq_obj.status == "operativo":
                    # Use a special status to indicate a pending request.  This
                    # prevents the unit from being counted as available in the
                    # dashboard until it is processed.
                    eq_obj.set_status("en solicitud")
                # Persist after adding a new request and updating the fleet status
                save_data()
                st.success(f"Solicitud enviada (ID {req_id})")

    # Tab 2: Tracking requests and orders
    with tabs[2]:
        st.subheader("Seguimiento de solicitudes y órdenes")
        # Table of work requests
        if st.session_state.work_requests:
            req_rows = []
            for req in st.session_state.work_requests:
                req_rows.append(
                    {
                        "ID solicitud": req["id"],
                        "Equipo": req["equipment_id"],
                        "Componente": req["component_name"],
                        "Criticidad": req["classification"],
                        "Fecha": req["date"],
                        "Estado": req["status"],
                    }
                )
            st.write("Solicitudes")
            st.table(req_rows)
        else:
            st.info("No hay solicitudes registradas.")
        # Table of work orders (pending and completed)
        if st.session_state.scheduler.pending_orders:
            ot_rows = []
            for ot in st.session_state.scheduler.pending_orders:
                ot_rows.append(
                    {
                        "ID OT": ot.id,
                        "Equipo": ot.equipment_id,
                        "Componente": ot.component_name,
                        "Criticidad": getattr(ot, "classification", ""),
                        "Fecha programa": ot.due_date,
                        "Estado": ot.status,
                    }
                )
            st.write("Órdenes de trabajo")
            st.table(ot_rows)
        else:
            st.info("No hay órdenes de trabajo registradas.")

    # Tab 3: Checklist (update readings)
    with tabs[3]:
        st.subheader("Checklist diario de horómetro y odómetro")
        update_readings_form()

    # Tab 4: Failure history
    with tabs[4]:
        st.subheader("Historial de fallas")
        if not st.session_state.failure_log.entries:
            st.info("No hay fallas registradas.")
        else:
            # Allow filtering by equipment
            eq_choices = list({entry[1] for entry in st.session_state.failure_log.entries})
            eq_choices.sort()
            eq_filter = st.selectbox(
                "Equipo", ["Todos"] + eq_choices, key="ops_fail_filter"
            )
            fail_rows = []
            for ts, eq_id, comp, desc, repair_h in st.session_state.failure_log.entries:
                if eq_filter != "Todos" and eq_id != eq_filter:
                    continue
                fail_rows.append(
                    {
                        "Fecha": ts.strftime("%Y-%m-%d %H:%M"),
                        "Equipo": eq_id,
                        "Componente": comp,
                        "Descripción": desc,
                        "Horas reparación": repair_h,
                    }
                )
            if fail_rows:
                st.table(fail_rows)
            else:
                st.info("No hay fallas para el equipo seleccionado.")

    # Tab 5: Availability report
    with tabs[5]:
        st.subheader("Reporte de disponibilidad de la flota")
        # Compute counts
        total, available, due_soon, in_maintenance = fleet_summary()
        # Compute unique fail equipment (pending alta requests)
        fail_eq = {
            req["equipment_id"]
            for req in st.session_state.work_requests
            if req["status"] == "pendiente" and req["classification"] == "alta"
        }
        failure = len(fail_eq)
        counts = {
            "Disponible": available,
            "En mantenimiento": in_maintenance,
            "Próx. mantenimiento": due_soon,
            "Falla": failure,
        }
        df_counts = pd.DataFrame.from_dict(counts, orient="index", columns=["Cantidad"])
        st.bar_chart(df_counts)


def process_work_requests() -> None:
    """Process pending work requests from operations.

    For each request the maintenance user can reclassify the
    criticity and assign a due date.  On conversion, a new work
    order is added to the scheduler and the operations user is
    notified.  Requests remain in the list with status set to
    'procesada' so they are not processed again.
    """
    if not st.session_state.work_requests:
        st.info("No hay solicitudes de mantenimiento pendientes.")
        return
    for req in list(st.session_state.work_requests):
        if req["status"] != "pendiente":
            continue
        with st.expander(
            f"Solicitud {req['id']} – Equipo {req['equipment_id']} ({req['component_name']})"
        ):
            st.write(f"Fecha reporte: {req['date']}")
            st.write(f"Lectura horómetro: {req['horometro']} h")
            st.write(f"Criticidad sugerida: {req['classification']}")
            st.write(f"Comentarios: {req['comments']}")
            if req.get("photo_name"):
                st.write(f"Adjunto: {req['photo_name']}")
            # Reclassification
            new_class = st.selectbox(
                "Asignar criticidad",
                ["alta", "media", "baja"],
                index=["alta", "media", "baja"].index(req["classification"]),
                key=f"reclass_{req['id']}"
            )
            # Ask for due date and time separately to give operators full control.  The time
            # is entered manually as HH:MM and validated.  If invalid it falls back to 00:00.
            due_date = st.date_input(
                "Programar para (fecha)", value=datetime.date.today(), key=f"due_{req['id']}"
            )
            due_time_str = st.text_input(
                "Programar para (hora HH:MM)", value="08:00", key=f"due_time_{req['id']}"
            )
            if st.button("Convertir a OT", key=f"conv_{req['id']}"):
                reason = f"Solicitud de operaciones: {req['comments']}"
                # Parse due time safely
                try:
                    due_time = datetime.datetime.strptime(due_time_str, "%H:%M").time()
                except ValueError:
                    due_time = datetime.time(0, 0)
                    st.warning("Formato de hora inválido para la programación de la OT. Use HH:MM")
                # Create the work order without the classification argument to maintain compatibility
                ot = WorkOrder(
                    equipment_id=req["equipment_id"],
                    component_name=req["component_name"],
                    due_date=due_date,
                    reason=reason,
                )
                # Attach due time to the order
                try:
                    setattr(ot, "due_time", due_time)
                except Exception:
                    pass
                # Set classification attribute explicitly (not all versions of WorkOrder accept it in constructor)
                try:
                    ot.classification = new_class
                except Exception:
                    # If classification cannot be set, ignore
                    pass
                st.session_state.scheduler.pending_orders.append(ot)
                # Mark equipment as in maintenance
                equipment = st.session_state.fleet.get(req["equipment_id"])
                if equipment:
                    equipment.set_status("en mantenimiento")
                # Log this as a failure in the failure log to build an accurate history.
                try:
                    desc = req.get("comments", "Falla reportada por operaciones")
                    st.session_state.failure_log.log_failure(
                        req["equipment_id"],
                        req["component_name"],
                        desc,
                        0.0,
                    )
                except Exception:
                    pass
                req["status"] = "procesada"
                req["classification"] = new_class
                # Append notification for operations
                st.session_state.notifications_ops.append(
                    f"Solicitud {req['id']} convertida en OT {ot.id} con criticidad '{new_class}'"
                )
                # Persist changes (work request processed, OT created and failure logged)
                save_data()
                st.success(f"OT {ot.id} creada a partir de la solicitud {req['id']}")


def manage_orders() -> None:
    """Display and manage pending work orders.

    Maintenance users can adjust criticity and due date, complete
    orders recording materials used and start/end times, and
    optionally delete or cancel orders.
    """
    # Heading is provided by the caller; avoid duplicating it here.
    pending = [o for o in st.session_state.scheduler.pending_orders if o.status == "pendiente"]
    if not pending:
        st.info("No hay órdenes pendientes.")
        return
    for ot in pending:
        with st.expander(f"OT {ot.id} – Equipo {ot.equipment_id} ({ot.component_name})"):
            st.write(f"Creada: {ot.created_at.date()}")
            st.write(f"Programada para: {ot.due_date}")
            st.write(f"Razón: {ot.reason}")
            current_class = getattr(ot, "classification", "")
            st.write(f"Criticidad actual: {current_class}")
            # Edit criticidad and due date
            new_class = st.selectbox(
                "Modificar criticidad",
                ["alta", "media", "baja"],
                index=["alta", "media", "baja"].index(getattr(ot, "classification", "alta") or "alta"),
                key=f"edit_class_{ot.id}"
            )
            new_due = st.date_input(
                "Modificar fecha programada", value=ot.due_date, key=f"edit_due_{ot.id}"
            )
            if st.button("Guardar cambios", key=f"save_ot_{ot.id}"):
                try:
                    ot.classification = new_class
                except Exception:
                    pass
                ot.due_date = new_due
                st.session_state.notifications_ops.append(
                    f"OT {ot.id} reclasificada a '{new_class}' y reprogramada"
                )
                # Persist the updated order to disk
                save_data()
                st.success(f"OT {ot.id} actualizada")
            # Completion
            # Gather data for completion: start time, end time, materials and comments
            # Provide a neutral default time (00:00) to encourage the user to select
            # the appropriate values rather than relying on the current time.
            default_start_time = getattr(ot, "start_time", None)
            default_end_time = getattr(ot, "completed_at", None)
            # Use stored times if present; otherwise default to midnight
            start_def_time = default_start_time.time() if default_start_time else datetime.time(0, 0)
            end_def_time = default_end_time.time() if default_end_time else datetime.time(0, 0)
            # Time inputs: allow the user to type the time directly in HH:MM
            # format for greater flexibility.  If the input cannot be
            # parsed, fall back to the default time (00:00) and show a
            # warning.  This avoids issues where the time picker does
            # not accept keyboard input on some platforms.
            start_time_str = st.text_input(
                "Hora de inicio (HH:MM)",
                value=start_def_time.strftime("%H:%M"),
                key=f"start_time_str_{ot.id}"
            )
            try:
                start_time = datetime.datetime.strptime(start_time_str, "%H:%M").time()
            except ValueError:
                start_time = start_def_time
                st.warning("Formato de hora de inicio inválido. Use HH:MM")
            end_time_str = st.text_input(
                "Hora de término (HH:MM)",
                value=end_def_time.strftime("%H:%M"),
                key=f"end_time_str_{ot.id}"
            )
            try:
                end_time = datetime.datetime.strptime(end_time_str, "%H:%M").time()
            except ValueError:
                end_time = end_def_time
                st.warning("Formato de hora de término inválido. Use HH:MM")
            current_mats = getattr(ot, "materials_used", [])
            materials = st.text_input(
                "Materiales utilizados (separados por comas)",
                value=", ".join(current_mats),
                key=f"mat_{ot.id}"
            )
            comments = st.text_input(
                "Comentarios (opcional)",
                value=getattr(ot, "comments", ""),
                key=f"comments_{ot.id}"
            )
            if st.button("Marcar completada", key=f"comp_ot_{ot.id}"):
                # Parse materials list
                used = [m.strip() for m in materials.split(",") if m.strip()]
                # Assign dynamic attributes
                try:
                    setattr(ot, "materials_used", used)
                except Exception:
                    pass
                try:
                    setattr(ot, "comments", comments)
                except Exception:
                    pass
                # Combine date with time inputs (use due date as date)
                start_dt = datetime.datetime.combine(ot.due_date, start_time)
                end_dt = datetime.datetime.combine(ot.due_date, end_time)
                # Ensure chronological order
                if end_dt < start_dt:
                    end_dt = start_dt
                # Set status, times
                ot.status = "en progreso"
                ot.start_time = start_dt
                ot.completed_at = end_dt
                ot.status = "completada"
                # Update equipment status to operativo
                eq = st.session_state.fleet.get(ot.equipment_id)
                if eq:
                    eq.set_status("operativo")
                # Use scheduler to finalize the order (updates last service information)
                st.session_state.scheduler.complete_order(ot.id)
                # Notifications to operations
                start_str = ot.start_time.strftime("%Y-%m-%d %H:%M") if ot.start_time else "—"
                end_str = ot.completed_at.strftime("%Y-%m-%d %H:%M") if ot.completed_at else "—"
                mats = ", ".join(getattr(ot, "materials_used", [])) if getattr(ot, "materials_used", []) else "N/A"
                st.session_state.notifications_ops.append(
                    f"OT {ot.id} completada (inicio: {start_str}, fin: {end_str}, materiales: {mats})"
                )
                # Persist completion and removal from pending list
                save_data()
                st.success(f"OT {ot.id} completada")

def mechanic_orders() -> None:
    """Display work orders for mechanics to start, finish and report details.

    Mechanics can record the start and end times, materials used and comments
    for each pending order.  Completing an order via this interface sets
    the equipment status back to "operativo" and updates maintenance records.
    """
    pending = [o for o in st.session_state.scheduler.pending_orders if o.status == "pendiente"]
    if not pending:
        st.info("No hay órdenes pendientes.")
        return
    for ot in pending:
        with st.expander(f"OT {ot.id} – Equipo {ot.equipment_id} ({ot.component_name})"):
            st.write(f"Creada: {ot.created_at.date()}")
            st.write(f"Programada para: {ot.due_date}")
            st.write(f"Razón: {ot.reason}")
            st.write(f"Criticidad: {getattr(ot, 'classification', '')}")
            # Capture start and end time, materials and comments
            # Use stored times if present; otherwise default to midnight
            default_start_time = getattr(ot, "start_time", None)
            default_end_time = getattr(ot, "completed_at", None)
            start_def_time = default_start_time.time() if default_start_time else datetime.time(0, 0)
            end_def_time = default_end_time.time() if default_end_time else datetime.time(0, 0)
            # Allow one‑minute granularity for start and end times to give
            # mechanics full control over the recorded repair window.
            # Time inputs: allow free entry of HH:MM for greater flexibility.
            start_time_str = st.text_input(
                "Hora de inicio (HH:MM)",
                value=start_def_time.strftime("%H:%M"),
                key=f"m_start_str_{ot.id}"
            )
            try:
                start_time = datetime.datetime.strptime(start_time_str, "%H:%M").time()
            except ValueError:
                start_time = start_def_time
                st.warning("Formato de hora de inicio inválido. Use HH:MM")
            end_time_str = st.text_input(
                "Hora de término (HH:MM)",
                value=end_def_time.strftime("%H:%M"),
                key=f"m_end_str_{ot.id}"
            )
            try:
                end_time = datetime.datetime.strptime(end_time_str, "%H:%M").time()
            except ValueError:
                end_time = end_def_time
                st.warning("Formato de hora de término inválido. Use HH:MM")
            current_mats = getattr(ot, "materials_used", [])
            materials = st.text_input(
                "Materiales utilizados (separados por comas)",
                value=", ".join(current_mats),
                key=f"m_mat_{ot.id}"
            )
            comments = st.text_input(
                "Comentarios (opcional)",
                value=getattr(ot, "comments", ""),
                key=f"m_comments_{ot.id}"
            )
            if st.button("Cerrar trabajo", key=f"m_comp_{ot.id}"):
                used = [m.strip() for m in materials.split(",") if m.strip()]
                setattr(ot, "materials_used", used)
                setattr(ot, "comments", comments)
                start_dt = datetime.datetime.combine(ot.due_date, start_time)
                end_dt = datetime.datetime.combine(ot.due_date, end_time)
                if end_dt < start_dt:
                    end_dt = start_dt
                ot.status = "en progreso"
                ot.start_time = start_dt
                ot.completed_at = end_dt
                ot.status = "completada"
                # Mark equipment back to operativo
                eq = st.session_state.fleet.get(ot.equipment_id)
                if eq:
                    eq.set_status("operativo")
                # Finalize the order through scheduler
                st.session_state.scheduler.complete_order(ot.id)
                # Send notification to operations
                start_str = ot.start_time.strftime("%Y-%m-%d %H:%M") if ot.start_time else "—"
                end_str = ot.completed_at.strftime("%Y-%m-%d %H:%M") if ot.completed_at else "—"
                mats = ", ".join(getattr(ot, "materials_used", [])) if getattr(ot, "materials_used", []) else "N/A"
                st.session_state.notifications_ops.append(
                    f"OT {ot.id} completada (inicio: {start_str}, fin: {end_str}, materiales: {mats})"
                )
                # Persist changes
                save_data()
                st.success(f"Trabajo para OT {ot.id} completado")


def schedule_automatic_maintenance() -> None:
    """Trigger the scheduler to evaluate due maintenance by horómetro/km/time.

    This function calls the scheduler's built‑in method to
    generate scheduled orders automatically when component
    intervals are reached.  It is exposed as a button so that
    maintenance users can run it at the start of each day or
    shift.  In a production system this would run on a schedule
    (e.g. via a cron job or background task).
    """
    if st.button("Verificar órdenes programadas"):
        new_orders = st.session_state.scheduler.check_due_maintenance()
        # Persist any newly scheduled orders
        if new_orders:
            save_data()
            st.success(f"Se generaron {len(new_orders)} OT programadas.")
        else:
            st.info("No se generaron nuevas OT programadas.")


def manual_order_form() -> None:
    """Form for manual creation of scheduled orders by maintenance.

    Allows maintenance users to create an OT without a work
    request, specifying equipment, component, criticity and due
    date.  The reason can also be entered.  This is useful
    when scheduling tasks based on calendars or other criteria.
    """
    # Heading is provided by the caller; avoid duplicating it here.
    if not st.session_state.fleet:
        st.info("No hay equipos disponibles.")
        return
    eq_sel = st.selectbox("Equipo", list(st.session_state.fleet.keys()), key="manual_ot_eq")
    # Select system and component for the manual OT
    categories = list(st.session_state.component_categories.keys())
    system_sel = st.selectbox("Sistema", categories, key="manual_ot_sys")
    comp_options = st.session_state.component_categories.get(system_sel, [])
    if comp_options:
        comp_sel = st.selectbox(
            "Componente", comp_options, key="manual_ot_comp"
        )
    else:
        comp_sel = st.text_input(
            "Componente", key="manual_ot_comp_text"
        )
    classification = st.selectbox(
        "Criticidad", ["alta", "media", "baja"], key="manual_ot_class"
    )
    # Request both date and time for the scheduled intervention.  The time
    # cannot be selected via a native time picker on all platforms, so we
    # use a text field and parse the value.  If parsing fails the
    # appointment defaults to midnight.  The due_date is still stored in
    # the WorkOrder object for compatibility; the time is attached as a
    # separate attribute.
    due_date = st.date_input(
        "Programar para (fecha)", value=datetime.date.today(), key="manual_ot_due"
    )
    due_time_str = st.text_input(
        "Programar para (hora HH:MM)", value="08:00", key="manual_ot_due_time"
    )
    reason = st.text_input("Motivo de la OT", key="manual_ot_reason")
    if st.button("Crear OT", key="manual_ot_submit"):
        # Determine component name from selection or text input
        component_name = comp_sel
        # Parse due time safely
        try:
            due_time = datetime.datetime.strptime(due_time_str, "%H:%M").time()
        except ValueError:
            due_time = datetime.time(0, 0)
            st.warning("Formato de hora inválido para la programación. Use HH:MM")
        # Create the work order without classification argument for broader compatibility
        ot = WorkOrder(
            equipment_id=eq_sel,
            component_name=component_name,
            due_date=due_date,
            reason=reason or "OT programada manualmente",
        )
        # Attach the scheduled time as an attribute on the order
        try:
            setattr(ot, "due_time", due_time)
        except Exception:
            pass
        # Assign classification attribute explicitly
        try:
            ot.classification = classification
        except Exception:
            pass
        st.session_state.scheduler.pending_orders.append(ot)
        # Mark equipment as in maintenance when a manual OT is created
        eq_obj = st.session_state.fleet.get(eq_sel)
        if eq_obj:
            eq_obj.set_status("en mantenimiento")
        st.session_state.notifications_ops.append(
            f"OT {ot.id} creada manualmente para equipo {eq_sel} con criticidad '{classification}'"
        )
        # Persist the new manual OT
        save_data()
        st.success(f"OT {ot.id} creada")


def maintenance_view() -> None:
    """Render the interface for maintenance users.

    This view is organised into tabs for clarity.  The first tab
    presents a dashboard shared with operations users.  Subsequent
    tabs allow maintenance staff to process requests from
    operations, run the automatic scheduler, create manual work
    orders, manage existing orders, maintain the inventory and
    register new equipment, log failures and compute reliability
    metrics, and review overall availability in a bar chart.
    """
    st.header("Mantenimiento")
    # Manual refresh button to reload the app state.  This allows the user
    # to pull the latest persisted data when automatic refresh is not
    # available or when the streamlit_autorefresh extension is not installed.
    if st.button("Refrescar ahora", key="mtto_refresh_btn"):
        st.experimental_rerun()

    # Enable automatic refresh every 5 seconds so that maintenance users
    # see new requests, orders or status changes without needing to
    # manually reload the page.  This mirrors the auto‑refresh
    # behaviour in the operations view.  When the optional
    # `streamlit_autorefresh` extension is available it will refresh
    # the page at the specified interval.  If the extension is not
    # installed, this call is silently ignored.
    try:
        from streamlit_autorefresh import st_autorefresh  # type: ignore

        st_autorefresh(interval=5000, key="mtto_autorefresh")
    except Exception:
        pass

    # Enable automatic refresh every 5 seconds for the maintenance view as
    # well, so that new work requests or status changes from other
    # sessions are picked up automatically.  If streamlit_autorefresh
    # is not installed, this call is silently ignored.
    try:
        from streamlit_autorefresh import st_autorefresh  # type: ignore

        st_autorefresh(interval=5000, key="mtto_autorefresh")
    except Exception:
        pass
    # Define the tabs for the maintenance view
    tabs = st.tabs(
        [
            "Resumen",
            "Solicitudes",
            "Programación automática",
            "Crear OT",
            "Órdenes",
            "Trabajos",  # nuevo tab para mecánicos
            "Inventario & Flota",
            "Registro de fallas",
            "Métricas & Confiabilidad",
            "Disponibilidad",
        ]
    )
    # Tab 0: Summary dashboard
    with tabs[0]:
        st.subheader("Resumen de flota")
        display_dashboard()
        # Detect whether new items have been added for maintenance users.  We
        # consider a pending request or newly scheduled order as an item of
        # interest.  When the total number of such items increases compared
        # to the last recorded count, play an alert sound.  This allows
        # mechanics to be notified of new work without constantly watching
        # the notifications list.
        pending_reqs = sum(1 for r in st.session_state.work_requests if r.get("status") == "pendiente")
        pending_ots = len(st.session_state.scheduler.pending_orders)
        current_count = pending_reqs + pending_ots
        if current_count > st.session_state.last_notif_count_mtto:
            # Play an alert sound and display a visual warning when new
            # work has been added (either a new request or a new OT).
            play_alert_sound()
            diff = current_count - st.session_state.last_notif_count_mtto
            st.warning(
                f"Se han recibido {diff} nuevas solicitudes u órdenes de trabajo. "
                "Revise las pestañas de Solicitudes u Órdenes para más detalles."
            )
        st.session_state.last_notif_count_mtto = current_count
    # Tab 1: Process requests
    with tabs[1]:
        st.subheader("Solicitudes pendientes de operaciones")
        process_work_requests()
    # Tab 2: Automatic scheduling
    with tabs[2]:
        st.subheader("Programación automática por horómetro/kilometraje/tiempo")
        schedule_automatic_maintenance()
    # Tab 3: Manual OT creation
    with tabs[3]:
        st.subheader("Crear OT programada manualmente")
        manual_order_form()
    # Tab 4: Manage existing OTs
    with tabs[4]:
        st.subheader("Órdenes de trabajo pendientes")
        manage_orders()
    # Tab 5: Work orders for mechanics to report completion
    with tabs[5]:
        st.subheader("Trabajos en ejecución (mecánicos)")
        mechanic_orders()
    # Tab 6: Inventory and equipment management
    with tabs[6]:
        st.subheader("Inventario de repuestos")
        inventory = st.session_state.inventory
        if inventory._stock:
            rows = []
            for part_name, (qty, min_qty) in inventory._stock.items():
                rows.append({"Repuesto": part_name, "Stock": qty, "Mínimo": min_qty})
            st.table(rows)
            low = inventory.low_stock_alerts()
            if low:
                st.warning(
                    "Repuestos con stock bajo: "
                    + ", ".join([f"{p} (stock {inventory.get_stock(p)})" for p in low])
                )
        else:
            st.info("No hay repuestos registrados.")
        # Form to add new spare parts – no component compatibility selection
        with st.form(key="add_part_form_roles"):
            st.write("Añadir nuevo repuesto")
            name = st.text_input("Nombre del repuesto", key="add_part_name")
            initial = st.number_input(
                "Stock inicial", min_value=0, step=1, value=0, key="add_part_initial"
            )
            min_stock = st.number_input(
                "Stock mínimo", min_value=0, step=1, value=0, key="add_part_min"
            )
            submitted = st.form_submit_button("Añadir repuesto")
            if submitted and name:
                # Always pass an empty list for fits_components to keep the API signature
                inventory.add_part(name, initial, min_stock, [])
                # Persist updated inventory
                save_data()
                st.success(f"Repuesto '{name}' añadido al inventario")
        # Equipment registration form
        add_equipment_form()
    # Tab 7: Failure logging
    with tabs[7]:
        st.subheader("Registro de fallas")
        fl = st.session_state.failure_log
        # Log a failure
        with st.form(key="fail_log_roles"):
            st.write("Registrar nueva falla")
            if not st.session_state.fleet:
                st.info("No hay equipos disponibles")
            else:
                eq_id = st.selectbox(
                    "Equipo", list(st.session_state.fleet.keys()), key="fail_roles_eq"
                )
                categories = list(st.session_state.component_categories.keys())
                system_sel = st.selectbox(
                    "Sistema", categories, key="fail_roles_sys"
                )
                comp_options = st.session_state.component_categories.get(system_sel, [])
                if comp_options:
                    comp_name = st.selectbox(
                        "Componente", comp_options, key="fail_roles_comp"
                    )
                else:
                    comp_name = st.text_input(
                        "Componente", key="fail_roles_comp_text"
                    )
                description = st.text_input("Descripción de la falla", key="fail_roles_desc")
                repair_hours = st.number_input(
                    "Horas de reparación", min_value=0.0, step=0.5, key="fail_roles_hours"
                )
                logged = st.form_submit_button("Registrar falla")
                if logged:
                    fl.log_failure(eq_id, comp_name, description, repair_hours)
                    save_data()
                    st.success(f"Falla registrada para equipo {eq_id}")
        # Display failure history with filter
        if fl.entries:
            st.write("Historial de fallas")
            eq_choices = list({entry[1] for entry in fl.entries})
            eq_choices.sort()
            eq_filter = st.selectbox(
                "Filtrar por equipo", ["Todos"] + eq_choices, key="fail_hist_filter"
            )
            rows = []
            for ts, eq_id, comp, desc, repair_h in fl.entries:
                if eq_filter != "Todos" and eq_id != eq_filter:
                    continue
                rows.append(
                    {
                        "Fecha": ts.strftime("%Y-%m-%d %H:%M"),
                        "Equipo": eq_id,
                        "Componente": comp,
                        "Descripción": desc,
                        "Horas reparación": repair_h,
                    }
                )
            if rows:
                st.table(rows)
                # Button to download as CSV
                df_fails = pd.DataFrame(rows)
                csv = df_fails.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Descargar historial CSV",
                    data=csv,
                    file_name="historial_fallas.csv",
                    mime="text/csv",
                )
            else:
                st.info("No hay fallas para el filtro seleccionado.")
        else:
            st.info("No hay fallas registradas.")

    # Tab 8: Reliability metrics
    with tabs[8]:
        st.subheader("Métricas y confiabilidad")
        fl = st.session_state.failure_log
        # Compute and display metrics only if there are logged failures
        if fl.entries:
            # Extract unique equipment IDs
            eq_ids = sorted({entry[1] for entry in fl.entries})
            # === Global metrics by equipment ===
            st.markdown("**Métricas globales por equipo**")
            global_rows = []
            for eq in eq_ids:
                # Global MTBF/MTTR across all components
                mtbf_eq = fl.calculate_mtbf(eq, None)
                mttr_eq = fl.calculate_mttr(eq, None)
                # Count failures for this equipment
                cnt = sum(1 for e in fl.entries if e[1] == eq)
                global_rows.append(
                    {
                        "Equipo": eq,
                        "Fallas": cnt,
                        "MTBF": mtbf_eq if mtbf_eq is not None else 0,
                        "MTTR": mttr_eq if mttr_eq is not None else 0,
                    }
                )
            df_global = pd.DataFrame(global_rows)
            # Bar chart: number of failures per equipment
            st.write("Número de fallas por equipo")
            st.bar_chart(df_global.set_index("Equipo")["Fallas"])
            # Line chart: MTBF and MTTR per equipment
            st.write("MTBF y MTTR por equipo (horas)")
            st.line_chart(df_global.set_index("Equipo")[["MTBF", "MTTR"]])
            # Download global metrics
            st.download_button(
                label="Descargar métricas globales CSV",
                data=df_global.to_csv(index=False).encode("utf-8"),
                file_name="metricas_globales.csv",
                mime="text/csv",
            )
            st.markdown("---")
            # === Detailed metrics by component for selected equipment ===
            st.markdown("**Detalles por equipo y componente**")
            eq_sel = st.selectbox(
                "Seleccione un equipo para ver detalles", eq_ids, key="metrics_eq"
            )
            # Compute metrics per component for the selected equipment
            comp_names = sorted({entry[2] for entry in fl.entries if entry[1] == eq_sel})
            mtbf_vals = []
            mttr_vals = []
            fail_counts = []
            for comp in comp_names:
                mtbf = fl.calculate_mtbf(eq_sel, comp)
                mttr = fl.calculate_mttr(eq_sel, comp)
                count = sum(1 for e in fl.entries if e[1] == eq_sel and e[2] == comp)
                mtbf_vals.append(mtbf if mtbf is not None else 0)
                mttr_vals.append(mttr if mttr is not None else 0)
                fail_counts.append(count)
            data = {
                "Componente": comp_names,
                "Fallas": fail_counts,
                "MTBF": mtbf_vals,
                "MTTR": mttr_vals,
            }
            df_detail = pd.DataFrame(data)
            if not df_detail.empty:
                st.write("Número de fallas por componente")
                st.bar_chart(df_detail.set_index("Componente")["Fallas"])
                st.write("MTBF y MTTR (horas)")
                st.line_chart(df_detail.set_index("Componente")[["MTBF", "MTTR"]])
                # Reliability curve for selected equipment using exponential model
                overall_mtbf = fl.calculate_mtbf(eq_sel, None)
                if overall_mtbf and overall_mtbf > 0:
                    st.write("Curva de confiabilidad (modelo exponencial)")
                    import numpy as np
                    import matplotlib.pyplot as plt
                    times = np.linspace(0, overall_mtbf * 3, 100)
                    rel = np.exp(-times / overall_mtbf)
                    fig, ax = plt.subplots()
                    ax.plot(times, rel)
                    ax.set_xlabel("Horas de operación")
                    ax.set_ylabel("Confiabilidad R(t)")
                    ax.set_title(f"Confiabilidad para {eq_sel} (MTBF = {overall_mtbf:.1f} h)")
                    st.pyplot(fig)
                else:
                    st.info("No se dispone de MTBF global para trazar la confiabilidad.")
                st.download_button(
                    label=f"Descargar métricas de {eq_sel}",
                    data=df_detail.to_csv(index=False).encode("utf-8"),
                    file_name=f"metricas_{eq_sel}.csv",
                    mime="text/csv",
                )
            else:
                st.info("El equipo seleccionado no tiene fallas registradas.")
        else:
            st.info("No se han registrado fallas; no hay métricas disponibles.")

    # Tab 9: Availability report
    with tabs[9]:
        st.subheader("Reporte de disponibilidad de la flota")
        total, available, due_soon, in_maintenance = fleet_summary()
        fail_eq = {
            req["equipment_id"]
            for req in st.session_state.work_requests
            if req["status"] == "pendiente" and req["classification"] == "alta"
        }
        failure = len(fail_eq)
        counts = {
            "Disponible": available,
            "En mantenimiento": in_maintenance,
            "Próx. mantenimiento": due_soon,
            "Falla": failure,
        }
        df_counts = pd.DataFrame.from_dict(counts, orient="index", columns=["Cantidad"])
        st.bar_chart(df_counts)


def main() -> None:
    """Entry point for the Streamlit application.

    Configure the application with a red and white colour scheme and
    initialise the session state before rendering the role‑based
    interface.  Users select their role from the sidebar and are
    presented with a tailored set of tabs.  Both roles share a
    summary dashboard, while maintenance and operations each
    present distinct functionality under separate tabs.
    """
    # Configure the page.  Older versions of Streamlit do not support
    # the ``theme`` keyword argument, so we call ``set_page_config``
    # without it and inject custom CSS below to approximate a
    # red/white palette.
    st.set_page_config(
        page_title="Gestión de Mantenimiento (Roles)",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_state()
    # Inject custom CSS to emulate a red and white colour scheme.  The
    # ``theme`` parameter is not available in older Streamlit
    # installations, so we use CSS to override some styles.  This
    # will colour headings and buttons in red and set the page
    # background to white.
    st.markdown(
        """
        <style>
        /* Page background and default text */
        .stApp {
            background-color: #ffffff;
            color: #333333;
        }
        /* Red headings */
        h1, h2, h3, h4, h5, h6 {
            color: #c62828;
        }
        /* Buttons */
        .stButton>button {
            background-color: #c62828;
            color: #ffffff;
        }
        /* Sidebar headings */
        .css-1v0mbdj h1, .css-1v0mbdj h2, .css-1v0mbdj h3 {
            color: #c62828;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    # ---------------------------------------------------------------------
    # Display company logo in the sidebar if available.  This is shown
    # regardless of login status.
    if os.path.exists(LOGO_PATH):
        # Use a try/except in case the image cannot be loaded.  Set
        # ``use_column_width`` to True to scale the logo to the sidebar width.
        try:
            st.sidebar.image(LOGO_PATH, use_column_width=True)
        except Exception:
            pass
    # ---------------------------------------------------------------------
    # Simple authentication mechanism.  If the user is not logged in,
    # present a login form in the sidebar.  Once authenticated, the
    # appropriate view is rendered based on the role associated with
    # their credentials.  Additionally, once logged in the user can
    # change their password from the sidebar.
    if not st.session_state.get("logged_in", False):
        st.sidebar.title("Inicio de sesión")
        with st.sidebar.form("login_form"):
            username = st.text_input("Usuario", key="login_user")
            password = st.text_input("Contraseña", type="password", key="login_pass")
            login_submitted = st.form_submit_button("Entrar")
        if login_submitted:
            user_entry = USERS.get(username)
            if user_entry and user_entry["password"] == password:
                st.session_state.logged_in = True
                st.session_state.user = username
                st.session_state.role = user_entry["role"]
                st.sidebar.success(f"Bienvenido, {username}")
                # Rerun to load the appropriate view
                st.experimental_rerun()
            else:
                st.sidebar.error("Credenciales incorrectas")
        # Show a message on the main page while waiting for login
        st.title("Gestión de Mantenimiento de Flota – Inicio de sesión")
        st.write(
            "Ingrese sus credenciales en la barra lateral para acceder a la aplicación."
        )
        return
    else:
        # Logged in: display user info, change password form and logout option
        current_user = st.session_state.user
        current_role = st.session_state.role
        st.sidebar.write(f"Usuario: {current_user} ({current_role})")
        # Password change expander
        with st.sidebar.expander("Cambiar contraseña"):
            with st.form("change_pass_form"):
                old_pass = st.text_input("Contraseña actual", type="password")
                new_pass = st.text_input("Nueva contraseña", type="password")
                confirm_pass = st.text_input("Confirmar nueva contraseña", type="password")
                change_submitted = st.form_submit_button("Actualizar contraseña")
            if change_submitted:
                user_entry = USERS.get(current_user)
                if user_entry and user_entry["password"] == old_pass:
                    if not new_pass:
                        st.warning("La nueva contraseña no puede estar vacía")
                    elif new_pass != confirm_pass:
                        st.warning("La nueva contraseña y su confirmación no coinciden")
                    else:
                        # Update password in the USERS dictionary and persist it
                        USERS[current_user]["password"] = new_pass
                        # Persist changes to disk so that the new password is
                        # available for future sessions and other devices.
                        save_data()
                        st.success("Contraseña actualizada correctamente")
                else:
                    st.error("La contraseña actual es incorrecta")
        # Logout button
        if st.sidebar.button("Cerrar sesión"):
            for key in ["logged_in", "user", "role"]:
                st.session_state.pop(key, None)
            st.experimental_rerun()
        # Show main title and description
        st.title("Gestión de Mantenimiento de Flota – Roles")
        st.write(
            "Seleccione las pestañas para acceder a las funciones disponibles. "
            "Tanto mantenimiento como operaciones comparten un resumen de la flota."
        )
        # Route to the appropriate interface based on the authenticated role.
        role = st.session_state.role
        if role == "Mantenimiento":
            maintenance_view()
        else:
            operations_view()


if __name__ == "__main__":
    main()